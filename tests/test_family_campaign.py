"""Tests for running families: runner interventions, provenance denial, campaign cases.

These cover the seam between ``tools/family.py`` (plan + verify) and the paid campaign
lane (``tools/run_suite.py`` -> ``arena.py`` -> ``env_runner.py``).  Nothing here calls
a provider or builds a container: the parts under test are argument plumbing, the
pre-judge integrity gate, case construction, and report semantics - all decidable from
files in this checkout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402

MOCO_EASY = "easy,easy,easy,easy,easy,easy"
MOCO_NO_HINTS = "easy,easy,medium,medium,easy,easy"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd or ROOT), text=True, capture_output=True
    )


@pytest.fixture(scope="module")
def family_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("family") / "moco"
    proc = _run(
        "tools/family.py", "--env", "moco", "--difficulty", MOCO_EASY,
        "--seeds", "3,4", "--interventions", "terminology,retrieval_cue",
        "--out", str(out),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


@pytest.fixture(scope="module")
def suite_manifest(family_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("family") / "suite.json"
    proc = _run("tools/suite_inventory.py", "--family", str(family_dir), "--preflight",
                "--out", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the runner applies interventions and records identity
# ---------------------------------------------------------------------------

def _reset(episode_id: str, *extra: str) -> dict:
    proc = _run(
        "env_runner.py", "reset", "--env", "moco", "--difficulty", MOCO_EASY,
        "--seed", "3", "--episode-id", episode_id, "--sandbox", "local", *extra,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_runner_regenerates_a_twin_and_records_both_identities() -> None:
    base_id, twin_id = "causalbase", "causaltwin"
    try:
        base = _reset(base_id)
        twin = _reset(twin_id, "--interventions", "terminology")
        base_info, twin_info = base["info"], twin["info"]
        assert base_info["interventions"] == []
        assert twin_info["interventions"] == ["terminology"]
        assert base_info["provenance"] == "recorded"
        assert twin_info["generation_id"] != base_info["generation_id"]
        # One task, two artifacts: this is the property a family run exists to test.
        assert twin_info["pair_id"] == base_info["pair_id"]

        state = env_runner._load_state(twin_id)
        assert state["interventions"] == ["terminology"]
        assert state["provenance"]["equivalences"] == ["semantically_equivalent"]
        events = [
            json.loads(line)
            for line in (ROOT / ".episodes" / twin_id / "environment-events.jsonl")
            .read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reset_event = next(event for event in events if event.get("event") == "reset")
        assert reset_event["interventions"] == ["terminology"]
        assert reset_event["generation_id"] == twin_info["generation_id"]
    finally:
        for episode_id in (base_id, twin_id):
            shutil.rmtree(ROOT / ".episodes" / episode_id, ignore_errors=True)


def test_provenance_gate_lets_the_agent_edit_and_denies_everything_else() -> None:
    episode_id = "causalprove"
    try:
        _reset(episode_id, "--interventions", "retrieval_cue")
        state = env_runner._load_state(episode_id)
        assert env_runner._verify_provenance(state) == []

        workspace = Path(state["workspace"])
        target = next(path for path in sorted(workspace.glob("*.py")))
        original = target.read_text(encoding="utf-8")
        target.write_text(original + "\n# the agent's patch\n", encoding="utf-8")
        # Editing the workspace is the task, so it must not read as tampering.
        assert env_runner._verify_provenance(state) == []
        target.write_text(original, encoding="utf-8")

        judge = Path(state["env_dir"]) / "judge" / "judge.py"
        judge_original = judge.read_text(encoding="utf-8")
        judge.write_text(
            judge_original.replace("def main(", "def main_hand_edit(", 1), encoding="utf-8"
        )
        problems = env_runner._verify_provenance(state)
        assert any("judge/judge.py" in problem for problem in problems), problems
        judge.write_text(judge_original, encoding="utf-8")

        # The pristine copy is what the submission is diffed against: if it moved,
        # the patch is not a patch on the instance that was graded.
        pristine = Path(state["original_workspace"])
        next(iter(sorted(pristine.glob("*.py")))).write_text("tampered\n", encoding="utf-8")
        problems = env_runner._verify_provenance(state)
        assert any("pristine" in problem for problem in problems), problems
    finally:
        shutil.rmtree(ROOT / ".episodes" / episode_id, ignore_errors=True)


def test_missing_interventions_on_a_twin_episode_is_a_denial_not_a_silent_base() -> None:
    """An episode that forgot to ask for its overlay must not be scored as the twin."""
    episode_id = "causalforgot"
    try:
        _reset(episode_id)
        state = env_runner._load_state(episode_id)
        # The campaign planned a twin; the runner was told nothing.  The record and the
        # request disagree, and that is exactly what the gate exists to catch.
        state["interventions"] = ["terminology"]
        problems = env_runner._verify_provenance(state)
        assert any("interventions applied" in problem for problem in problems), problems
    finally:
        shutil.rmtree(ROOT / ".episodes" / episode_id, ignore_errors=True)


# ---------------------------------------------------------------------------
# campaign cases
# ---------------------------------------------------------------------------

def test_family_cases_carry_the_pair_into_the_suite_manifest(suite_manifest: dict) -> None:
    assert suite_manifest["family_count"] == 1
    assert suite_manifest["ready_for_scheduler"] is True
    assert suite_manifest["case_count"] == 6
    by_intervention = {
        case["interventions"]: case for case in suite_manifest["cases"]
    }
    assert set(by_intervention) == {"", "terminology", "retrieval_cue"}
    twin = by_intervention["terminology"]
    assert twin["family"]["twin_check"] == "pass"
    assert twin["family"]["expect"] == "invariant"
    assert twin["family"]["equivalences"] == ["semantically_equivalent"]
    assert twin["family"]["baseline_case_id"].endswith("__baseline__seed-3") or twin[
        "family"
    ]["baseline_case_id"].endswith("__baseline__seed-4")
    assert all(case["status"] == "ready" for case in suite_manifest["cases"])
    # Task identity is shared by every member of a seed pair and differs across seeds.
    pairs = {
        (case["seed"], case["interventions"]): case["family"]["pair_id"]
        for case in suite_manifest["cases"]
    }
    assert pairs[(3, "")] == pairs[(3, "terminology")] == pairs[(3, "retrieval_cue")]
    assert pairs[(3, "")] != pairs[(4, "")]


def test_arena_command_passes_interventions_to_the_controller(suite_manifest: dict) -> None:
    from tools.run_suite import _build_command

    kwargs = dict(
        provider="openai", model="m", api_key_env="K", secrets=None, api_base=None,
        sandbox="docker", output_dir=Path("/tmp/out"), max_steps=10, max_tokens=100,
        invalid_retries=0, keep_images=False, keep_workspace=False,
    )
    for case in suite_manifest["cases"]:
        command = _build_command(case, **kwargs)
        if case["interventions"]:
            index = command.index("--interventions")
            assert command[index + 1] == case["interventions"]
        else:
            assert "--interventions" not in command


def test_a_family_whose_declaration_failed_is_not_schedulable(tmp_path: Path) -> None:
    """Inert overlay -> twin_check fails -> the campaign refuses the case."""
    family = tmp_path / "inert"
    proc = _run(
        "tools/family.py", "--env", "moco", "--difficulty", MOCO_NO_HINTS, "--seeds", "5",
        "--interventions", "retrieval_cue", "--allow-advisory", "--out", str(family),
    )
    # Non-zero: a family that fails its own verification is refused at the planning
    # step too.  The manifest is still written, which is what lets the inventory show
    # *why* the case is blocked rather than silently omitting it.
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert (family / "family_manifest.json").is_file()
    out = tmp_path / "suite.json"
    proc = _run("tools/suite_inventory.py", "--family", str(family), "--out", str(out))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["ready_for_scheduler"] is False
    blocked = [case for case in manifest["cases"] if case["status"] == "blocked_twin_check"]
    assert [case["interventions"] for case in blocked] == ["retrieval_cue"]
    assert "twin check reported 'fail'" in manifest["issues"][0]


def test_inventory_refuses_a_family_generated_from_a_changed_config(
    family_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "suite.json"
    proc = _run("tools/suite_inventory.py", "--family", str(family_dir), "--out", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads(out.read_text(encoding="utf-8"))
    # Pin a case to a config hash it cannot match: the scheduler must stop rather than
    # run a member that no longer exists as described.
    manifest["cases"][0]["config_sha256"] = "0" * 64
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps(manifest), encoding="utf-8")
    from tools.run_suite import _current_config_hash

    case = manifest["cases"][0]
    assert _current_config_hash(ROOT, case) != case["config_sha256"]


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

def _checkpoint(suite_manifest: dict, scores: dict[str, float]) -> dict:
    rows = []
    for case in suite_manifest["cases"]:
        family = case["family"]
        score = scores.get(case["case_id"])
        rows.append(
            {
                "case_id": case["case_id"],
                "environment": case["environment"],
                "status": "scored" if score is not None else "infrastructure_error",
                "verdict": None if score is None else ("PASS" if score >= 1 else "FAIL"),
                "score": score,
                "failure_mode": "pass" if score == 1.0 else ("underfit" if score is not None else "reward_denial"),
                "pair_id": family["pair_id"],
                "generation_id": family["generation_id"],
                "interventions": [part for part in (case["interventions"] or "").split(",") if part],
            }
        )
    return {"results": rows, "run": {}}


def test_the_report_reads_declarations_not_just_numbers(
    suite_manifest: dict, tmp_path: Path
) -> None:
    scores = {}
    for case in suite_manifest["cases"]:
        baseline = case["interventions"] == ""
        if baseline:
            scores[case["case_id"]] = 1.0
        elif case["family"]["expect"] == "invariant":
            scores[case["case_id"]] = 1.0  # unchanged: the invariance held
        else:
            scores[case["case_id"]] = 0.0  # moved: cue dependence
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(_checkpoint(suite_manifest, scores)), encoding="utf-8")
    report_path = tmp_path / "report.json"
    proc = _run(
        "tools/family_report.py", "--manifest", str(tmp_path / "unused.json"),
        "--checkpoint", str(checkpoint), "--json", str(report_path),
    )
    assert proc.returncode == 2  # a manifest with no family cases is refused
    manifest_path = tmp_path / "suite.json"
    manifest_path.write_text(json.dumps(suite_manifest), encoding="utf-8")
    proc = _run(
        "tools/family_report.py", "--manifest", str(manifest_path),
        "--checkpoint", str(checkpoint), "--json", str(report_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    verdicts = {entry["case_id"]: entry["verdict"] for entry in report["entries"]}
    assert set(verdicts.values()) == {"reference", "invariance_observed", "sensitivity_observed"}
    pooled = report["by_intervention"]
    assert pooled["terminology"]["mean_score_delta"] == 0.0
    assert pooled["retrieval_cue"]["directions"]["moved"] == 2
    assert report["planned_pair_count"] == 4
    assert "behavioral_association_only" in report["claim_ceiling"]


def test_an_unattributable_episode_is_reported_not_zeroed(
    suite_manifest: dict, tmp_path: Path
) -> None:
    scores = {case["case_id"]: 1.0 for case in suite_manifest["cases"]}
    checkpoint_data = _checkpoint(suite_manifest, scores)
    # A provenance denial is an integrity failure: no verdict about the model exists.
    for row in checkpoint_data["results"]:
        if row["case_id"] == suite_manifest["cases"][1]["case_id"]:
            row["status"] = "infrastructure_error"
            row["score"] = None
            row["failure_mode"] = "reward_denial"
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(checkpoint_data), encoding="utf-8")
    manifest_path = tmp_path / "suite.json"
    manifest_path.write_text(json.dumps(suite_manifest), encoding="utf-8")
    proc = _run(
        "tools/family_report.py", "--manifest", str(manifest_path),
        "--checkpoint", str(checkpoint), "--strict",
    )
    assert proc.returncode == 1
    assert "produced no usable verdict" in proc.stderr
    assert "not_measurable" in proc.stdout


def test_identity_drift_between_plan_and_run_is_visible(
    suite_manifest: dict, tmp_path: Path
) -> None:
    scores = {case["case_id"]: 1.0 for case in suite_manifest["cases"]}
    checkpoint_data = _checkpoint(suite_manifest, scores)
    for row in checkpoint_data["results"]:
        if row["case_id"] == suite_manifest["cases"][1]["case_id"]:
            row["pair_id"] = "P" + "0" * 17
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(checkpoint_data), encoding="utf-8")
    manifest_path = tmp_path / "suite.json"
    manifest_path.write_text(json.dumps(suite_manifest), encoding="utf-8")
    report_path = tmp_path / "report.json"
    proc = _run(
        "tools/family_report.py", "--manifest", str(manifest_path),
        "--checkpoint", str(checkpoint), "--json", str(report_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    drifted = [
        entry for entry in report["entries"] if entry["verdict"] == "identity_mismatch"
    ]
    assert len(drifted) == 1
    assert drifted[0]["pair_id_stable"] is False


def test_the_report_attaches_trajectory_shifts_to_pair_verdicts(
    suite_manifest: dict, tmp_path: Path
) -> None:
    """Same score, different route: the pair must not read as a plain invariance."""
    baseline_case, member_case = suite_manifest["cases"][0], suite_manifest["cases"][1]
    for case, kinds in ((baseline_case, ["observe", "retrieve"]), (member_case, ["observe"])):
        run_dir = tmp_path / str(case["case_id"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "environment-events.jsonl").write_text(
            "\n".join(
                json.dumps({
                    "ts": 1.0, "event": "step", "schema": 1, "action_kind": kind,
                    "action": {"type": "read_file"},
                })
                for kind in kinds
            )
            + "\n",
            encoding="utf-8",
        )
    scores = {case["case_id"]: 1.0 for case in suite_manifest["cases"]}
    checkpoint_data = _checkpoint(suite_manifest, scores)
    for row in checkpoint_data["results"]:
        if row["case_id"] in (baseline_case["case_id"], member_case["case_id"]):
            row["run_dir"] = str(tmp_path / row["case_id"])
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(checkpoint_data), encoding="utf-8")
    manifest_path = tmp_path / "suite.json"
    manifest_path.write_text(json.dumps(suite_manifest), encoding="utf-8")
    report_path = tmp_path / "report.json"
    proc = _run(
        "tools/family_report.py", "--manifest", str(manifest_path),
        "--checkpoint", str(checkpoint), "--json", str(report_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entry = next(
        item for item in report["entries"] if item["case_id"] == member_case["case_id"]
    )
    assert entry["verdict"] == "invariance_observed"
    assert entry["trajectory"]["status"] == "measured"
    assert entry["trajectory_shift"]["count_delta"]["retrieve"] == -1
    unmeasured = [
        item for item in report["entries"]
        if item.get("role") == "member"
        and item["trajectory_shift"]["status"] == "not_measurable"
    ]
    assert len(unmeasured) == 3
    assert report["trajectory"]["pairs_measured"] == 1
    assert report["trajectory"]["pairs_total"] == 4


def test_generated_member_records_remain_verifiable_after_the_whole_chain(
    family_dir: Path,
) -> None:
    """Nothing in the campaign path may mutate a planned member in place."""
    manifest = json.loads((family_dir / gm.FAMILY_MANIFEST_NAME).read_text(encoding="utf-8"))
    for member in manifest["members"]:
        ok, errors = gm.verify_manifest(family_dir / member["path"], config_root=ROOT)
        assert ok, (member["name"], errors)
        record = gm.read_manifest(family_dir / member["path"])
        assert record["generation_id"] == member["generation_id"]
        assert record["pair_id"] == member["pair_id"]


# ---------------------------------------------------------------------------
# registry-direct (intervention, view) expansion
# ---------------------------------------------------------------------------

_RUN_SUITE_KWARGS = dict(
    provider="openai", model="m", api_key_env="K", secrets=None, api_base=None,
    sandbox="docker", output_dir=Path("/tmp/out"), max_steps=10, max_tokens=100,
    invalid_retries=0, keep_images=False, keep_workspace=False,
)


def test_inventory_expands_one_case_per_intervention_and_view(tmp_path: Path) -> None:
    """The evaluator tier becomes schedulable from the registry, without a family dir."""
    out = tmp_path / "suite_iv.json"
    proc = _run("tools/suite_inventory.py", "--matrix", "representative",
                "--interventions", "--out", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["selection"]["expand_interventions"] is True

    moco = [case for case in manifest["cases"] if case["environment"] == "moco"]
    by_iid = {case.get("interventions", ""): case for case in moco}
    assert set(by_iid) == {
        "", "terminology", "retrieval_cue", "visible_proxy", "evaluator", "reward_proxy",
    }
    baseline = by_iid[""]
    assert "intervention" not in baseline
    for iid, case in by_iid.items():
        if not iid:
            continue
        assert case["status"] == "planned"
        assert case["baseline_case_id"] == baseline["case_id"]
        assert case["case_id"].endswith(f"__{iid}__seed-{baseline['seed']}")
        assert case["difficulty"] == baseline["difficulty"]

    # A view-mechanism intervention carries the measurement it selects: that is the
    # "view" half of the (intervention, view) case, and it needs no second artifact.
    assert by_iid["evaluator"]["intervention"]["view"] == "behavioral_gated"
    assert by_iid["evaluator"]["intervention"]["equivalence"] == "evaluator_changing"
    assert by_iid["reward_proxy"]["intervention"]["view"] == "integrity_gated"
    assert by_iid["terminology"]["intervention"]["view"] is None
    # Declarations come from the taxonomy, which an environment may not relabel.
    assert by_iid["terminology"]["intervention"]["equivalence"] == "semantically_equivalent"
    assert by_iid["terminology"]["intervention"]["expect"] == "invariant"
    assert by_iid["retrieval_cue"]["intervention"]["expect"] == "sensitive"
    assert by_iid["visible_proxy"]["intervention"]["defect_class"] == "A_false"

    # An environment that declares no interventions is untouched by the expansion.
    rope = [case for case in manifest["cases"] if case["environment"] == "rope"]
    assert len(rope) == 1 and "intervention" not in rope[0]
    assert manifest["intervention_case_count"] == sum(
        1 for case in manifest["cases"] if case.get("intervention")
    ) > 0

    # The expanded cases are schedulable through the same builder families use.
    from tools.run_suite import _build_command

    command = _build_command(by_iid["terminology"], **_RUN_SUITE_KWARGS)
    assert command[command.index("--interventions") + 1] == "terminology"


def test_intervention_expansion_is_opt_in(family_dir: Path, tmp_path: Path) -> None:
    """Default inventories keep their case list; families refuse a second expansion."""
    default_out = tmp_path / "suite_default.json"
    proc = _run("tools/suite_inventory.py", "--matrix", "representative",
                "--out", str(default_out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = json.loads(default_out.read_text(encoding="utf-8"))
    assert manifest["selection"]["expand_interventions"] is False
    assert manifest["intervention_case_count"] == 0
    assert all(not case.get("interventions") for case in manifest["cases"])

    duplicate = tmp_path / "suite_dup.json"
    proc = _run("tools/suite_inventory.py", "--family", str(family_dir),
                "--interventions", "--out", str(duplicate))
    assert proc.returncode == 2
    assert "already are the intervention expansion" in proc.stderr


def test_expanded_view_case_survives_preflight_generation(tmp_path: Path) -> None:
    """Preflighting an intervention case generates the twin, not the baseline."""
    import tools.suite_inventory as si

    case = {
        "case_id": "moco__probe__evaluator__seed-0",
        "environment": "moco",
        "difficulty_levels": {axis["id"]: "easy" for axis in
                              si._load_yaml(ROOT / "envs/moco/config.yaml")["axes"]},
        "seed": 0,
        "interventions": "evaluator",
    }
    result = si._preflight_case(case, ROOT)
    assert result["status"] == "ready", result
