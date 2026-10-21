"""The manual-dispatch study is only safe if its refusals are real.

Ten provider-free properties are pinned here.  They are the ones a dispatcher
depends on and that a careless edit would quietly remove:

1. the curated diagnostic matrix actually contains every condition the study
   claims to test (baseline, cyclic SAT, cyclic UNSAT with non-empty local
   tables, opaque labels, decoy, maximum depth, held-out seed, strength-2
   interaction) and nothing is silently dropped;
2. a ceiling below the worst case is an error, not a warning, so no dispatch can
   authorise more spend than it declared;
3. case identity is stable and the plan is deterministic, so a case id in a
   report always names the same generated instance;
4. shards partition the case list exactly once - the whole-family rerun path;
5. family scope drops members the exact-instance gate cannot certify, names them
   with a reason, and never relabels them compile-only;
6. a run refuses a manifest that smuggled an uncertified environment back in,
   before the controller (and therefore before any provider access) is created;
7. the operator's ceilings reach the controller verbatim - they are never
   rounded up, and the gate leg is requested explicitly;
8. the report never pools the expanded control with the recursive discovery
   condition (or any two environments) into one score;
9. every failure class the study distinguishes stays distinct, and a timeout, a
   missing row, a provider error or an oracle failure is never a score and never
   read as unsatisfiability;
10. the agent-facing prompts of both diagnostic environments are free of the
    banned vocabulary and do not leak the judge's hidden check names.

An eleventh test pins the manual-copy workflow contract, because the workflow
file is the only artefact that cannot be produced by this checkout.
"""
from __future__ import annotations

import copy
import itertools
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import recursive_gluing_study as study  # noqa: E402
from tools.recursive_references import reference_environments  # noqa: E402
from tools.suite_inventory import _case_id  # noqa: E402

CREATED_AT = "2026-10-20T00:00:00Z"


def _manifest(**overrides):
    params = {
        "scope": "diagnostic",
        "provider": "atria",
        "model": "atria-dawn-preview",
        "wire_api": "responses",
        "created_at": CREATED_AT,
    }
    params.update(overrides)
    return study.build_study_manifest(**params)


def _row(case_id: str, tmp: Path, *, final: dict, **overrides) -> dict:
    run_dir = tmp / f"run_{abs(hash(case_id)) % 10**8}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "final.json").write_text(json.dumps(final), encoding="utf-8")
    (run_dir / "model_responses.jsonl").write_text(
        json.dumps({"usage": {"prompt_tokens": 11, "completion_tokens": 7}}) + "\n",
        encoding="utf-8",
    )
    row = {
        "case_id": case_id,
        "status": "scored",
        # The checkpoint row is what the controller recorded; the judge's own
        # verdict comes from final.json.  Keep them consistent unless the row
        # deliberately disagrees (the provider/infrastructure rows do).
        "verdict": final.get("verdict"),
        "score": final.get("score"),
        "failure_mode": final.get("failure_mode"),
        "run_dir": str(run_dir),
        "elapsed_seconds": 1.5,
        "http_attempts": 2,
        "judge_guarantee": "container",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. The curated diagnostic matrix is complete
# ---------------------------------------------------------------------------


def test_diagnostic_matrix_contains_every_required_condition() -> None:
    manifest, plan = _manifest()
    cases = manifest["cases"]
    assert plan["case_count"] == len(cases) == 18
    assert plan["provider_free"] is True and plan["worst_case"]["api_calls"] > 0
    assert {case["environment"] for case in cases} == set(study.PRIMARY)
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert plan["seeds"] == [0, 1]

    def has(environment: str, **levels: str) -> bool:
        return any(
            case["environment"] == environment
            and all(case["difficulty_levels"].get(axis) == level for axis, level in levels.items())
            for case in cases
        )

    # SAT baseline (tree, readable labels) and cyclic SAT.
    assert has("recursive_gluing", recursive_depth="easy", gluing_regime="easy", label_opacity="easy")
    assert has("recursive_gluing", gluing_regime="medium")
    assert has("recursive_gluing_discovery", gluing_regime="medium")
    # Cyclic UNSAT whose local tables stay non-empty, in both conditions.
    assert has("recursive_gluing", gluing_regime="hard", label_opacity="easy")
    assert has("recursive_gluing_discovery", gluing_regime="hard", label_opacity="easy")
    # Opaque labels, the decoy leaf, and the maximum intended depth.
    assert has("recursive_gluing", label_opacity="hard")
    assert has("recursive_gluing_discovery", label_opacity="hard")
    assert has("recursive_gluing_discovery", structural_ambiguity="hard")
    assert has("recursive_gluing", recursive_depth="hard", state_space="hard")
    assert has("recursive_gluing_discovery", recursive_depth="hard", state_space="hard")
    # Held-out/fixed seeds: seed 1 exists and is labelled as a stability cell.
    stability = [case for case in cases if case["seed"] == 1]
    assert stability and all("stability" in case["study"]["factor"] for case in stability)
    # Strength-2 interaction that separates "copy the local table upward" from
    # reconstructing the composition rule: obstruction x opacity under depth.
    interaction = [
        case
        for case in cases
        if case["study"]["factor"] == "opacity_x_unsat"
    ]
    assert len(interaction) == 2, "one interaction cell per diagnostic environment"
    for case in interaction:
        levels = case["difficulty_levels"]
        assert sum(1 for level in levels.values() if level != "easy") >= 2
        assert levels["label_opacity"] == "hard"
        assert levels["gluing_regime"] == "hard"


# ---------------------------------------------------------------------------
# 2. A ceiling below the worst case is an error, not a warning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"max_api_calls": 10}, "max_api_calls"),
        ({"max_tokens_total": 1000}, "max_tokens_total"),
        ({"max_wall_seconds": 60}, "max_wall_seconds"),
    ],
)
def test_plan_refuses_ceilings_below_the_worst_case(overrides, needle) -> None:
    with pytest.raises(study.StudyError) as excinfo:
        _manifest(**overrides)
    assert needle in str(excinfo.value)
    assert "does not fit the declared ceilings" in str(excinfo.value)


def test_plan_rejects_an_unbounded_wall_ceiling() -> None:
    with pytest.raises(study.StudyError) as excinfo:
        _manifest(max_wall_seconds=study.MAX_DISPATCH_WALL_SECONDS + 1)
    assert "dispatch_wall_cap" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Deterministic plan, stable case identity
# ---------------------------------------------------------------------------


def test_plan_is_deterministic_and_case_identity_is_stable() -> None:
    first, first_plan = _manifest()
    second, second_plan = _manifest()
    assert [case["case_id"] for case in first["cases"]] == [
        case["case_id"] for case in second["cases"]
    ]
    assert first["inventory"]["config_paths_sha256"] == second["inventory"]["config_paths_sha256"]
    assert first_plan == second_plan

    for case in first["cases"]:
        # The id is a pure function of (environment, axis levels, seed): a case
        # id in a report can never name two different generated instances.
        assert case["case_id"] == _case_id(
            case["environment"], case["difficulty_levels"], case["seed"]
        )
        # And the difficulty string follows the config's axis order exactly.
        config = yaml.safe_load((ROOT / case["config_path"]).read_text(encoding="utf-8"))
        ordered = [case["difficulty_levels"][axis["id"]] for axis in config["axes"]]
        assert case["difficulty"] == ",".join(ordered)
        assert case["config_sha256"]


# ---------------------------------------------------------------------------
# 4. Shards partition the case list exactly once
# ---------------------------------------------------------------------------


def test_shards_partition_the_family_case_list() -> None:
    full, full_plan = _manifest(
        scope="family",
        matrix="pairwise",
        max_api_calls=100_000,
        max_tokens_total=400_000_000,
        max_wall_seconds=study.MAX_DISPATCH_WALL_SECONDS,
    )
    assert full["study"]["shard"] == {"index": 0, "count": 1}
    assert full["study"]["full_case_count"] == full_plan["case_count"]

    shards = [
        _manifest(
            scope="family",
            matrix="pairwise",
            shard_index=index,
            shard_count=4,
            max_api_calls=100_000,
            max_tokens_total=400_000_000,
            max_wall_seconds=study.MAX_DISPATCH_WALL_SECONDS,
        )
        for index in range(4)
    ]
    ids = [case["case_id"] for manifest, _plan in shards for case in manifest["cases"]]
    assert len(ids) == len(set(ids)), "shards must be disjoint"
    assert set(ids) == {case["case_id"] for case in full["cases"]}
    for index, (manifest, plan) in enumerate(shards):
        assert manifest["study"]["shard"] == {"index": index, "count": 4}
        assert plan["shard"] == {"index": index, "count": 4}
        assert plan["case_count"] < full_plan["case_count"]

    with pytest.raises(study.StudyError):
        _manifest(scope="family", shard_index=4, shard_count=4)


# ---------------------------------------------------------------------------
# 5. Uncertified members are excluded, with a reason, never compile-only
# ---------------------------------------------------------------------------


def test_family_scope_excludes_uncertified_members_with_a_reason() -> None:
    manifest, plan = _manifest(
        scope="family",
        matrix="pairwise",
        max_api_calls=100_000,
        max_tokens_total=400_000_000,
        max_wall_seconds=study.MAX_DISPATCH_WALL_SECONDS,
    )
    excluded = {entry["environment"]: entry for entry in plan["excluded_environments"]}
    assert excluded, "at least one family member has no behavioural reference"
    for environment, entry in excluded.items():
        assert entry["reason"] == "no_behavioural_reference"
        assert entry["detail"], "an exclusion without a reason is not an exclusion"
        assert entry["dropped_case_count"] > 0
        assert environment not in reference_environments()

    live = {case["environment"] for case in manifest["cases"]}
    assert live <= set(reference_environments())
    assert all(case["condition"] != "compile_only" for case in manifest["cases"])
    assert plan["environments"] == sorted(live)
    # The study still reports the full registered family it was asked to cover.
    assert set(plan["environments"]) | set(excluded) == set(study.FAMILY)


# ---------------------------------------------------------------------------
# 6. A run refuses an uncertified environment before the controller exists
# ---------------------------------------------------------------------------


def test_run_refuses_an_uncertified_environment_before_the_controller() -> None:
    manifest, _plan = _manifest(max_api_calls=5_000, max_tokens_total=20_000_000)
    holonomy = next(iter(set(study.FAMILY) - set(reference_environments())))
    poisoned = copy.deepcopy(manifest)
    smuggled = copy.deepcopy(poisoned["cases"][0])
    smuggled["case_id"] = f"{holonomy}__smuggled"
    smuggled["environment"] = holonomy
    poisoned["cases"].append(smuggled)

    calls: list[dict] = []

    def runner(*args, **kwargs):  # pragma: no cover - must never run
        calls.append(kwargs)
        raise AssertionError("the controller must not be constructed")

    with pytest.raises(study.StudyError) as excinfo:
        study.run_study(
            poisoned,
            execution_mode="live",
            provider="atria",
            model="atria-dawn-preview",
            output_dir=Path("/tmp/should-not-exist"),
            runner=runner,
        )
    assert holonomy in str(excinfo.value)
    assert "compile-only" in str(excinfo.value)
    assert calls == []


# ---------------------------------------------------------------------------
# 7. Ceilings reach the controller verbatim; the gate leg is explicit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "execution_mode, stop_after_gates",
    [("gates_only", True), ("live", False)],
)
def test_run_forwards_ceilings_and_gate_leg_verbatim(execution_mode, stop_after_gates) -> None:
    manifest, plan = _manifest(max_api_calls=5_000, max_tokens_total=20_000_000)
    captured: dict = {}

    def runner(manifest_arg, **kwargs):
        captured["manifest"] = manifest_arg
        captured.update(kwargs)
        return {"results": [], "paused": False, "provider_free_validation_complete": True}

    ceilings = {
        "max_api_calls": plan["limits"]["max_api_calls"],
        "max_tokens_total": plan["limits"]["max_tokens_total"],
        "max_wall_seconds": plan["limits"]["max_wall_seconds"],
    }
    result = study.run_study(
        manifest,
        execution_mode=execution_mode,
        provider="atria",
        model="atria-dawn-preview",
        output_dir=Path("/tmp/study-run"),
        wire_api="responses",
        max_steps=study.DEFAULT_MAX_STEPS,
        max_tokens=study.DEFAULT_MAX_TOKENS,
        runner=runner,
        **ceilings,
    )
    assert result["checkpoint"]["paused"] is False
    assert captured["stop_after_gates"] is stop_after_gates
    assert captured["sandbox"] == "docker"
    assert captured["api_key_env"] == "SUITE_API_KEY", "a credential value must never be passed"
    for key, value in ceilings.items():
        assert captured[key] == value, f"{key} must not be adjusted"
    # A ceiling below the plan is refused here too, before the controller runs.
    with pytest.raises(study.StudyError):
        study.run_study(
            manifest,
            execution_mode=execution_mode,
            provider="atria",
            model="atria-dawn-preview",
            output_dir=Path("/tmp/study-run"),
            max_api_calls=1,
            runner=runner,
        )


# ---------------------------------------------------------------------------
# 8. The report never pools conditions or environments
# ---------------------------------------------------------------------------


def test_report_keeps_conditions_and_environments_separate(tmp_path: Path) -> None:
    manifest, _plan = _manifest()
    gluing, discovery = study.PRIMARY
    rows = []
    for case in manifest["cases"]:
        final = {
            "verdict": "PASS",
            "score": 1.0,
            "failure_mode": "pass",
            "checks": {"assembled_unsat": True, "obstructed_cycle": True},
            "metrics": {"recursive_depth": 1, "unfolded_occurrences": 7},
        }
        rows.append(_row(case["case_id"], tmp_path, final=final))
    report = study.build_report(
        manifest,
        {"results": rows, "run": {"provider": "atria", "model": "atria-dawn-preview"}},
        gate_report={"instance_coverage_complete": True, "provider_calls": 0},
    )
    assert report["schema_version"] == 1
    assert report["cross_condition_aggregation"] == "none"
    assert {entry["condition"] for entry in report["conditions"]} == {
        "expanded_control",
        "recursive_discovery",
    }
    by_condition = {entry["condition"]: entry for entry in report["conditions"]}
    assert by_condition["expanded_control"]["case_count"] + by_condition[
        "recursive_discovery"
    ]["case_count"] == len(manifest["cases"])
    assert all("score" not in entry for entry in report["conditions"])
    assert {entry["environment"] for entry in report["environments"]} == {gluing, discovery}
    # No top-level aggregate exists at all: nothing here can be quoted as "the"
    # score of the comparison.
    assert "score" not in report
    assert "overall" not in report and "pooled" not in report


# ---------------------------------------------------------------------------
# 9. Every failure class stays distinct; none of them is a score or an "unsat"
# ---------------------------------------------------------------------------


def test_report_classifies_outcomes_without_inventing_scores(tmp_path: Path) -> None:
    manifest, _plan = _manifest()
    cases = manifest["cases"]
    assert len(cases) >= 9
    scored_pass = {
        "verdict": "PASS",
        "score": 1.0,
        "failure_mode": "pass",
        "checks": {"obstructed_cycle": True},
    }
    wrong_decision = {
        "verdict": "FAIL",
        "score": 0.5,
        "failure_mode": "underfit",
        "checks": {"obstructed_cycle": False},
    }
    malformed = {"verdict": "FAIL", "score": 0.0, "failure_mode": "patch_invalid", "checks": {}}
    plan = [
        ("scored", {"verdict": "PASS", "score": 1.0, "failure_mode": "pass"}, study.OUTCOME_VALIDATED_SUCCESS),
        ("scored", {"verdict": "FAIL", "score": 0.4, "failure_mode": "underfit"}, study.OUTCOME_SCORED_FAILURE),
        ("scored", {"verdict": "FAIL", "score": 0.0, "failure_mode": "patch_invalid"}, study.OUTCOME_MALFORMED),
        ("scored", {"verdict": "FAIL", "score": 0.5, "failure_mode": "underfit", "checks": {"obstructed_cycle": False}}, study.OUTCOME_WRONG_DECISION),
        ("paused_provider_error", {"failure_mode": "api_error"}, study.OUTCOME_PROVIDER),
        ("infrastructure_error", {"failure_mode": "controller_error"}, study.OUTCOME_INFRASTRUCTURE),
        ("infrastructure_error", {"failure_mode": "judge_runtime_error"}, study.OUTCOME_ORACLE),
        ("scored", {"verdict": "FAIL", "score": 0.0, "failure_mode": "timeout"}, study.OUTCOME_TIMEOUT),
        ("scored", {"verdict": "FAIL", "score": 0.0, "failure_mode": "patch_invalid", "x": 1}, study.OUTCOME_COMPILE_ONLY),
    ]
    rows = []
    expected = {}
    for case, (status, final, outcome) in zip(cases, plan):
        row = _row(case["case_id"], tmp_path, final=final, status=status)
        if status != "scored":
            row["score"] = None
            row["verdict"] = None
        if case["environment"] == "recursive_gluing" and "obstructed_cycle" in final.get("checks", {}):
            row["judge_guarantee"] = "container"
        rows.append(row)
        expected[case["case_id"]] = outcome
    # One case is deliberately left without any row: absent is not unsat.
    missing_case = cases[-1]["case_id"]
    rows = [row for row in rows if row["case_id"] != missing_case]
    expected[missing_case] = study.OUTCOME_MISSING
    # The last row is a satisfied-but-unvalidated compile-only guarantee: it is
    # reported as such, never as a validated success.
    rows[-1]["judge_guarantee"] = "compile_only"

    report = study.build_report(
        manifest,
        {"results": rows},
        gate_report={"instance_coverage_complete": True},
    )
    observed = {entry["case_id"]: entry["outcome"] for entry in report["cases"]}
    for case_id, outcome in expected.items():
        assert observed[case_id] == outcome, case_id
    assert set(observed.values()) <= set(study.OUTCOMES)
    # A non-scored outcome never carries a score, and a compile-only row is not
    # counted among the environment's validated successes.
    for entry in report["cases"]:
        if entry["outcome"] in {
            study.OUTCOME_MISSING,
            study.OUTCOME_PROVIDER,
            study.OUTCOME_INFRASTRUCTURE,
            study.OUTCOME_ORACLE,
            study.OUTCOME_TIMEOUT,
            study.OUTCOME_COMPILE_ONLY,
        }:
            assert entry["outcome"] != study.OUTCOME_VALIDATED_SUCCESS
    by_env = {entry["environment"]: entry for entry in report["environments"]}
    for entry in by_env.values():
        assert entry["validated_success_count"] <= entry["scored_case_count"] + 1
    # A gate failure overrides every score: an uncertified run cannot report one.
    gated = study.build_report(
        manifest,
        {"results": rows},
        gate_report={"instance_coverage_complete": False},
    )
    assert {entry["outcome"] for entry in gated["cases"]} == {study.OUTCOME_ORACLE}


def test_classify_never_returns_an_unsatisfiability_verdict() -> None:
    for row, final in [
        (None, {}),
        ({"status": "paused_provider_error"}, {}),
        ({"status": "infrastructure_error", "failure_mode": "judge_runtime_error"}, {}),
        ({"status": "scored", "verdict": "FAIL", "score": 0.0, "failure_mode": "timeout"}, {}),
    ]:
        outcome = study.classify_result(row, final, decision_checks=("assembled_unsat",))
        assert "unsat" not in outcome and "sat" not in outcome


# ---------------------------------------------------------------------------
# 10. Prompts are leak-free
# ---------------------------------------------------------------------------


def test_prompts_are_free_of_banned_vocabulary_and_oracle_leaks() -> None:
    banned = ("sheaf", "global section", "holonomy", "category theory", "presheaf", "cohomology")
    leaks = (
        "network.py",
        "judge.py",
        "reference_certificate",
        "reference_solve",
        "assembled_unsat",
        "assembled_sat",
        "obstructed_cycle",
        "cyclic_unsat_generated",
        "arm_local_only",
    )
    for environment in study.PRIMARY:
        files = ROOT / "envs" / "cat_theo" / environment / "files"
        prompt = (files / "prompt.md").read_text(encoding="utf-8").lower()
        for term in banned:
            assert term not in prompt, f"{environment}: prompt leaks {term!r}"
        for term in leaks:
            assert term not in prompt, f"{environment}: prompt leaks the hidden name {term!r}"
        visible = (files / "visible_tests.py").read_text(encoding="utf-8")
        # The visible tests may exercise the contract, but must not contain the
        # judge's oracle or the held-out instance generators.
        for term in ("reference_certificate", "reference_solve", "network"):
            assert term not in visible, f"{environment}: visible_tests leaks {term!r}"


# ---------------------------------------------------------------------------
# 11. The workflow is a manual copy, and says so
# ---------------------------------------------------------------------------


def test_workflow_example_is_manual_dispatch_only() -> None:
    example = ROOT / "docs" / "workflows" / "recursive-gluing-eval.yml.example"
    note = ROOT / "docs" / "workflows" / "recursive-gluing-eval.md"
    assert example.is_file() and note.is_file()
    text = example.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}, "no schedule, no push, no self-dispatch"
    inputs = triggers["workflow_dispatch"]["inputs"]
    for name in (
        "scope",
        "execution_mode",
        "provider",
        "model",
        "matrix",
        "seeds",
        "max_api_calls",
        "max_tokens_total",
        "max_wall_seconds",
        "max_steps",
        "max_tokens",
    ):
        assert name in inputs, name
    assert inputs["execution_mode"]["default"] == "plan_only"
    assert set(inputs["execution_mode"]["options"]) == {"plan_only", "live"}
    assert workflow["permissions"] == {"contents": "read"}
    # No credential may appear in a command line: secret references live in
    # step-level `env:` blocks only.
    job = workflow["jobs"]["evaluate"]
    for step in job["steps"]:
        script = step.get("run") or ""
        assert "secrets." not in script, f"secret referenced from a shell step: {step.get('name')}"
    for step in job["steps"]:
        script = step.get("run") or ""
        # `set -e` plus `[ -n "$X" ] && args+=(...)` aborts the step whenever the
        # optional input is empty: the optional argument must be added in an if.
        assert "] && " not in script, f"{step.get('name')}: set -e would abort on an empty optional input"
    # Every shell step must parse: a workflow file is only half-validated by YAML.
    import subprocess

    for step in job["steps"]:
        script = step.get("run")
        if not script:
            continue
        parsed = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert parsed.returncode == 0, f"{step.get('name')}: {parsed.stderr}"
    provider_step = next(
        step for step in job["steps"] if step.get("name", "").startswith("Live evaluation")
    )
    assert any("API_KEY" in key or "_TOKEN" in key for key in provider_step["env"])
    # The workflow does not re-implement the harness: it only invokes the study
    # tool, which owns the controller call.
    for step in job["steps"]:
        script = step.get("run") or ""
        assert "tools/run_suite.py" not in script
        assert "env_runner" not in script

    deployment = note.read_text(encoding="utf-8")
    assert ".github/workflows/recursive-gluing-eval.yml" in deployment
    assert "docs/workflows/recursive-gluing-eval.yml.example" in deployment
    assert "manual" in deployment.lower()
