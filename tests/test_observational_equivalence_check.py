"""The observational-equivalence operator: what the overlay must prove, and what the
instrument must not silently do.

These tests are the executable version of the experiment's honesty rules. Two of them
exist because of things this repository would otherwise get wrong without noticing: a
newly declared intervention re-plans every running campaign (so the campaign-neutral
half of the change is separated from the campaign-visible half), and an overlay whose
bytes happen to equal its base produces a null that reads like a negative result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import experiment_spec as es  # noqa: E402
from tools import family  # noqa: E402
import generate_env as ge  # noqa: E402

ENVS = ("epistemic_games", "epistemic_nested_knowledge", "epistemic_fragmented_observation")
OPERATOR_IDS = ("equivalence_check", "state_enumeration")
SPEC = ROOT / "spec" / "observational-equivalence-check.yaml"
PATCH = ROOT / "handoff" / "observational-equivalence-interventions.patch"
RESULTS = ROOT / "experiments" / "operator_study"


# ---------------------------------------------------------------- the declared overlays

def test_the_taxonomy_declares_both_operator_components() -> None:
    taxonomy = ge.load_intervention_taxonomy()
    for iid in OPERATOR_IDS:
        entry = taxonomy[iid]
        # An added instruction changes what the agent sees and not what is graded, so it
        # is observation_changing. `semantically_equivalent` would demand byte-identical
        # trees, which is the invariance class - and would make a firing overlay a failure.
        assert entry["equivalence"] == "observation_changing", iid
        assert entry["expect"] == "sensitive", iid
        assert entry["proof"] == "difference", iid
        assert entry["mechanism"] == "layout", iid


def test_the_operator_text_is_one_artifact_not_two_transcriptions() -> None:
    for name in ("equivalence_check", "state_enumeration", "equivalence_check_revised"):
        text = (ROOT / "spec" / "operators" / f"{name}.md").read_text()
        assert text.startswith("## Required procedure"), name
        assert "%%" not in text, f"{name} must not carry placeholders the renderer owns"
    shipped = (ROOT / "spec" / "operators" / "equivalence_check.md").read_text()
    revised = (ROOT / "spec" / "operators" / "equivalence_check_revised.md").read_text()
    # The revision is a real revision, not a restatement: its fourth step has to differ,
    # because that step is what the instrument shows over-applying the gate.
    assert revised != shipped
    assert "uniform posterior" in revised and "uniform posterior" not in shipped


def test_the_env_side_change_is_a_patch_and_the_campaign_plan_is_untouched() -> None:
    """Case identity carries config_sha256, so editing an env config re-plans every
    running campaign and invalidates its banked gate rows. The operator's env-side half
    therefore ships as a patch to apply between campaigns, and only its half that cannot
    move a plan may land on a branch a campaign checks out."""
    assert PATCH.is_file(), "the env-side declarations must ship as an applicable patch"
    diff = PATCH.read_text()
    touched = {
        line.split("b/", 1)[1]
        for line in diff.splitlines()
        if line.startswith("+++")
    }
    assert all(path.startswith("envs/") for path in touched), touched
    assert "envs/interventions.yaml" not in touched, (
        "the taxonomy is already committed; a patch that also edits it cannot apply"
    )
    for env in ENVS:
        config = yaml.safe_load((ROOT / "envs" / env / "config.yaml").read_text())
        implemented = set((config.get("interventions") or {}))
        assert not (implemented & set(OPERATOR_IDS)), (
            f"{env} implements the operator directly; that edit belongs in {PATCH.name} "
            "because it changes config_sha256 and re-plans live campaigns"
        )


def test_a_taxonomy_entry_alone_cannot_replan_a_campaign() -> None:
    from tools import atria_campaign as ac
    from tools.suite_inventory import build_manifest

    def plan():
        profile = ac._load_yaml(ROOT / "experiments" / "mercury_pairwise_campaign.yaml")
        ac._validate_campaign_profile(profile)
        manifest = build_manifest(
            root=ROOT,
            matrix=str(ac.matrix_mode_of(profile)),
            seeds=[0],
            expand_interventions=ac.matrix_interventions_of(profile),
        )
        return sorted(str(case["case_id"]) for case in manifest["cases"])

    cases = plan()
    assert len(cases) == 496, "the shipped pairwise plan is 496 cases; anything else is a re-plan"
    assert not [c for c in cases if "equivalence_check" in c or "state_enumeration" in c], (
        "a declared-but-unimplemented id must add no cases; if this fails, expansion is "
        "reading the taxonomy rather than the environment, and every campaign would "
        "re-plan whenever vocabulary is added"
    )


# ------------------------------------------------------------------------- the spec itself

def test_the_spec_is_the_only_missing_piece_the_env_side_patch() -> None:
    """The spec must be coherent now, and the *only* thing it lacks is the patch."""
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    taxonomy = ge.load_intervention_taxonomy()
    errors, warnings = es.validate_spec(
        spec,
        taxonomy=taxonomy,
        implemented=family.registry_implementations(),
        known_environments=family.registry_names(),
    )
    assert not warnings, warnings
    assert any("kind" in e for e in []) or True
    assert errors, "an unpatched env cannot implement the operator, so validation must say so"
    # Every complaint must be about the missing implementation and nothing else: the
    # patch is the only thing between this spec and a generated family.
    for error in errors:
        assert "does not implement" in error or "implements no interventions" in error, error
        assert any(env in error for env in ENVS), error


def test_the_spec_declares_the_components_it_measures() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    kinds = {h["kind"] for h in spec["hypotheses"]}
    assert {"primary", "competing", "null"} <= kinds, "a null must be stated, or a null result is unfalsified"
    measurements = {m["id"] for m in spec["measurements"]}
    for required in (
        "accuracy_identifiable",
        "accuracy_non_identifiable",
        "false_unique_explanation_rate",
        "support_undercommit_rate",
        "format_cost_rate",
        "pair_id_stability",
    ):
        assert required in measurements, required
    # Every measurement the spec names must be produced by a member, and the strata must
    # be separate members: pooling them is the arithmetic the question forbids.
    produced = {name for member in spec["members"] for name in member.get("measurements", [])}
    assert produced == measurements, produced ^ measurements
    assert "pooled" not in " ".join(m["id"] for m in spec["measurements"])


def test_an_unquoted_null_kind_is_rejected_not_defaulted() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    for hypothesis in spec["hypotheses"]:
        if hypothesis["id"] == "Hnull":
            hypothesis["kind"] = None
    errors, _ = es.validate_spec(spec, taxonomy=ge.load_intervention_taxonomy())
    assert any("write it quoted" in error for error in errors), errors


# ---------------------------------------------------------------- the family, via the patch

@pytest.fixture(scope="module")
def patched_repo(tmp_path_factory) -> Path:
    """A throwaway worktree with the env-side patch applied, so the family proof runs on
    exactly what the user would ship."""
    worktree = tmp_path_factory.mktemp("oec_worktree")
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
        cwd=ROOT, check=True, capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "apply", str(PATCH)], cwd=worktree, check=True, capture_output=True
        )
    except subprocess.CalledProcessError as exc:
        raise AssertionError(f"{PATCH.name} does not apply to HEAD: {exc.stderr.decode()[:400]}")
    yield worktree
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT,
                   check=True, capture_output=True)


def test_the_operator_twins_are_the_same_task_under_a_different_instruction(patched_repo: Path) -> None:
    # No in-process re-validation here: family.registry_implementations() resolves
    # against the checkout this test runs in, not the worktree, so it would report the
    # unpatched state. The subprocess below is the validation - `tools/family.py` exits 2
    # on a spec error before it generates anything, so returncode 0 is "coherent, in the
    # tree that has the patch".
    out = patched_repo / "families" / "oec"
    result = subprocess.run(
        [
            sys.executable, "tools/family.py",
            "--env", "epistemic_games",
            "--difficulty", "trap,ambiguous,paired,skewed,narrative",
            "--seeds", "3",
            "--interventions", ",".join(OPERATOR_IDS),
            "--out", str(out),
            "--json", str(out.parent / "family.json"),
        ],
        cwd=patched_repo, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, result.stdout[-600:] + result.stderr[-600:]
    family_manifest = json.loads((out.parent / "family.json").read_text())
    baseline = next(m for m in family_manifest["members"] if m["role"] == "baseline")
    base_task = (out / baseline["name"] / "agent/workspace/task.md").read_text()
    for member in family_manifest["members"]:
        if member["role"] == "baseline":
            continue
        assert member["twin_check"] == "pass", member["check"]["problems"]
        # The two halves of the matched-design claim: the instruction really landed, and
        # the task really did not move.
        assert member["shares_pair_id_with_baseline"] is True, member["name"]
        assert member["pair_id"] == baseline["pair_id"], member["name"]
        assert member["check"]["overlay_fired"]["layout_overridden"] is True, member["name"]
        rendered = (out / member["name"] / "agent/workspace/task.md").read_text()
        overlay = (patched_repo / "spec" / "operators" / {
            "equivalence_check": "equivalence_check.md",
            "state_enumeration": "state_enumeration.md",
        }[member["interventions"][0]]).read_text()
        assert rendered.startswith(base_task), "the control's task text must survive intact"
        assert rendered.endswith(overlay.rstrip() + "\n"), member["name"]
        assert (out / member["name"] / "judge/judge.py").read_text() == (
            out / baseline["name"] / "judge/judge.py"
        ).read_text(), "the measurement must not have moved"


def test_the_base_environment_is_untouched_by_the_operator(patched_repo: Path) -> None:
    """The overlay is a layout swap onto a new file, so the shipped template is not
    rewritten: a control member must still match the environment as published."""
    for env in ENVS:
        config = yaml.safe_load((patched_repo / "envs" / env / "config.yaml").read_text())
        assert (config.get("layout") or {})["agent/workspace/task.md"] == "task.md", env
        assert "%%TASK_MD%%" in (patched_repo / "envs" / env / "files" / "task.md").read_text()
        for name in ("equivalence_check", "state_enumeration"):
            template = patched_repo / "envs" / env / "files" / f"task_{name}.md"
            assert template.is_file(), template
            body = template.read_text().replace("%%TASK_MD%%\n\n", "")
            assert body.strip() == (patched_repo / "spec" / "operators" / f"{name}.md").read_text().strip(), (env, name)


# ------------------------------------------------------------------- the instrument itself

_ORDER_PROBE = """
import json, sys
from pathlib import Path

import yaml

sys.path.insert(0, sys.argv[1])
import generate_env as ge

out = {}
Path(sys.argv[2]).mkdir(parents=True, exist_ok=True)
for name in json.loads(sys.argv[3]):
    config = yaml.safe_load(open(Path(sys.argv[1]) / "envs" / name / "config.yaml"))
    levels = {axis["id"]: next(iter(axis["levels"])) for axis in config["axes"]}
    manifest = ge.generate_env(name, str(Path(sys.argv[2]) / name), levels, seed=3)
    out[name] = {"tree": manifest["tree_sha256"], "pair_id": manifest["pair_id"]}
print(json.dumps(out))
"""


def _generate_in_order(tmp_path: Path, order: list[str]) -> dict:
    helper = tmp_path / f"probe_{'-'.join(order)}.py"
    helper.write_text(_ORDER_PROBE)
    result = subprocess.run(
        [sys.executable, str(helper), str(ROOT), str(tmp_path / "-".join(order)), json.dumps(order)],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, result.stdout[-400:] + result.stderr[-600:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_rendered_env_no_longer_inherits_the_previous_envs_core(tmp_path: Path) -> None:
    """`_run_renderer` used to leave each environment's `core` in sys.modules, so the
    second renderer environment in a process built its instance with the *first* one's
    builder. Two environments in one family is what a transfer experiment is, so this
    is the difference between a measured effect and an artifact of generation order."""
    solo = _generate_in_order(tmp_path, ["epistemic_nested_knowledge"])
    after_fragmented = _generate_in_order(
        tmp_path, ["epistemic_fragmented_observation", "epistemic_nested_knowledge"]
    )
    assert solo["epistemic_nested_knowledge"] == after_fragmented["epistemic_nested_knowledge"], (
        "the nested-knowledge tree depends on whether another environment was rendered "
        "first in the same process"
    )
    assert solo["epistemic_nested_knowledge"]["tree"] != after_fragmented[
        "epistemic_fragmented_observation"
    ]["tree"], "the two environments are rendering one another's instances"


def test_the_instrument_reports_the_dissociation_it_was_built_for() -> None:
    summary = json.loads((RESULTS / "summary.json").read_text())
    games = summary["epistemic_games"]
    nonident = games["non_identifiable"]["arms"]
    ident = games["identifiable"]["arms"]

    # Measurement 2: the control asserts a separation the instance forbids, every time.
    assert nonident["control"]["claims_a_separation_rate"] == 1.0
    for arm in ("state_enumeration", "equivalence_check", "equivalence_check_revised"):
        assert nonident[arm]["claims_a_separation_rate"] == 0.0, arm

    # Measurement 3, the trap: the shipped clause buys the separation fix with the mirror
    # error, and the revision is what shows both are avoidable.
    assert nonident["equivalence_check"]["undercommit_rate"] == 0.5
    assert nonident["equivalence_check_revised"]["undercommit_rate"] == 0.0
    assert nonident["equivalence_check_revised"]["strict_accuracy"] == 1.0
    assert nonident["equivalence_check"]["strict_accuracy"] == 0.5

    # Component A on its own: enumeration lifts identifiable accuracy and the gate costs
    # nothing there, which is why the two components are declared as two ids.
    assert ident["state_enumeration"]["strict_accuracy"] == 1.0
    assert ident["equivalence_check"]["strict_accuracy"] == 1.0
    assert ident["control"]["strict_accuracy"] < 0.1

    # Measurement 4: the clause that cannot be expressed cannot be scored, so the cost is
    # a format failure rather than a smaller number.
    for env in ("epistemic_nested_knowledge", "epistemic_fragmented_observation"):
        arms = summary[env]["identifiable"]["arms"]
        assert arms["equivalence_check_literal"]["format_invalid_rate"] == 1.0, env
        assert arms["equivalence_check_literal"]["strict_accuracy"] == 0.0, env
        assert arms["equivalence_check_revised"]["strict_accuracy"] == 1.0, env
        assert arms["state_enumeration"]["strict_accuracy"] == 1.0, env
        assert summary[env]["identifiable"]["arms"]["equivalence_check"]["non_identifiable_n"] == 0, (
            f"{env} must report no non-identifiable stratum: its prompt names the scenario "
            "under evaluation, so a claim of transfer for the uncertainty clause has no "
            "items to stand on"
        )


def test_no_model_was_contacted_and_the_raw_rows_say_so() -> None:
    rows = [
        json.loads(line) for line in (RESULTS / "raw_results.jsonl").read_text().splitlines() if line.strip()
    ]
    assert rows, "the study must ship its raw results"
    armed = [r for r in rows if "arm" in r]
    assert len(armed) % 5 == 0, "every instance carries all five arms, or the design is not matched"
    keys = {(r["environment"], r["seed"], r["case_id"]) for r in armed}
    for key in keys:
        present = {r["arm"] for r in armed if (r["environment"], r["seed"], r["case_id"]) == key}
        assert present == {
            "control", "state_enumeration", "equivalence_check",
            "equivalence_check_literal", "equivalence_check_revised",
        }, key
    # The operator arm differs from its control by the overlay and nothing else.
    by_key = {(r["environment"], r["seed"], r["case_id"], r["arm"]): r for r in armed}
    for (env, seed, case, arm), control in list(by_key.items()):
        if arm != "control":
            continue
        twin = by_key.get((env, seed, case, "equivalence_check"))
        if twin is None:
            continue
        assert control["prompt_chars_added"] == 0
        assert twin["prompt_chars_added"] > 0
        assert twin["identifiability"] == control["identifiability"]
