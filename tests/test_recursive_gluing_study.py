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
file is the only artefact that cannot be produced by this checkout, and a
twelfth pins the pause diagnosis: a stopped leg has to name its own cause on
the run page, because two live dispatches (39580706886, 39586680263) could not
be read at all - their only record was a checkpoint inside an artifact zip.
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
        "max_http_attempts": plan["limits"]["max_http_attempts"],
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
    assert captured["api_key_env"] == "ATRIA_API_KEY", "record the selected key env name, never its value"
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


def test_http_attempt_budget_is_derived_from_the_declared_ceiling() -> None:
    """A fixed tiny physical-attempt cap is a guaranteed mid-episode pause.

    Run 39580706886 (synapse_garden, live diagnostic) paused after 91s because
    the profile pinned the controller's *global* physical HTTP-attempt budget to
    6 while the plan declared 1,296 logical calls.  The budget must therefore
    scale with the operator's own ceiling, and be visible in the plan.
    """
    manifest, plan = _manifest(max_api_calls=5_000, max_tokens_total=20_000_000)
    captured: dict = {}

    def runner(_manifest, **kwargs):
        captured.update(kwargs)
        return {"results": [], "paused": False, "provider_free_validation_complete": True}

    study.run_study(
        manifest,
        execution_mode="gates_only",
        provider="synapse_garden",
        model="openai/gpt-6.1-sol",
        output_dir=Path("/tmp/study-run"),
        max_api_calls=plan["limits"]["max_api_calls"],
        max_tokens_total=plan["limits"]["max_tokens_total"],
        max_wall_seconds=plan["limits"]["max_wall_seconds"],
        runner=runner,
    )
    expected = plan["limits"]["max_api_calls"] * (1 + study.DEFAULT_MAX_RETRIES)
    assert captured["max_http_attempts"] == expected
    assert plan["limits"]["max_http_attempts"] == expected
    assert plan["limits"]["max_http_attempts_source"] == "derived"
    assert plan["limits"]["max_http_attempts"] >= plan["worst_case"]["api_calls"]
    check = next(c for c in plan["checks"] if c["name"] == "max_http_attempts")
    assert check["ok"] is True


def test_every_provider_gets_the_derived_budget_not_a_provider_specific_one() -> None:
    manifest, plan = _manifest(max_api_calls=5_000, max_tokens_total=20_000_000)
    forwarded = {}

    def recording_runner(provider: str):
        def runner(_manifest, **kwargs):
            forwarded[provider] = kwargs["max_http_attempts"]
            return {"results": [], "paused": False, "provider_free_validation_complete": True}

        return runner

    for provider, model in (("atria", "atria-dawn-preview"), ("synapse_garden", "openai/gpt-6.1-sol")):
        study.run_study(
            manifest,
            execution_mode="gates_only",
            provider=provider,
            model=model,
            output_dir=Path("/tmp/study-run"),
            max_api_calls=plan["limits"]["max_api_calls"],
            max_tokens_total=plan["limits"]["max_tokens_total"],
            max_wall_seconds=plan["limits"]["max_wall_seconds"],
            runner=recording_runner(provider),
        )
    assert forwarded == {
        "atria": plan["limits"]["max_http_attempts"],
        "synapse_garden": plan["limits"]["max_http_attempts"],
    }


def test_an_http_attempt_budget_below_the_plan_is_refused_provider_free() -> None:
    with pytest.raises(study.StudyError) as excinfo:
        _manifest(max_http_attempts=6)
    assert "max_http_attempts" in str(excinfo.value)

    manifest, _plan = _manifest(max_api_calls=5_000, max_tokens_total=20_000_000)
    calls: list[dict] = []

    def runner(_manifest, **kwargs):  # pragma: no cover - must never run
        calls.append(kwargs)
        raise AssertionError("the controller must not be constructed")

    with pytest.raises(study.StudyError) as excinfo:
        study.run_study(
            manifest,
            execution_mode="live",
            provider="synapse_garden",
            model="openai/gpt-6.1-sol",
            output_dir=Path("/tmp/should-not-exist"),
            max_http_attempts=6,
            runner=runner,
        )
    assert "max_http_attempts" in str(excinfo.value)
    assert calls == []


def test_an_explicit_http_attempt_budget_is_forwarded_verbatim() -> None:
    manifest, plan = _manifest(
        max_api_calls=5_000, max_tokens_total=20_000_000, max_http_attempts=4_000
    )
    captured: dict = {}

    def runner(_manifest, **kwargs):
        captured.update(kwargs)
        return {"results": [], "paused": False, "provider_free_validation_complete": True}

    study.run_study(
        manifest,
        execution_mode="live",
        provider="synapse_garden",
        model="openai/gpt-6.1-sol",
        output_dir=Path("/tmp/study-run"),
        max_api_calls=plan["limits"]["max_api_calls"],
        max_tokens_total=plan["limits"]["max_tokens_total"],
        max_wall_seconds=plan["limits"]["max_wall_seconds"],
        runner=runner,
    )
    assert plan["limits"]["max_http_attempts"] == 4_000
    assert plan["limits"]["max_http_attempts_source"] == "explicit"
    assert captured["max_http_attempts"] == 4_000


def test_a_paused_dispatch_is_legible_from_the_report_alone() -> None:
    """Run 39580706886 failed with exit 3 and its summary said nothing about it.

    A paused leg is not a result, but its reason and the rows that never became
    scores have to be in the artifact: the run log is not uploaded.
    """
    manifest, _plan = _manifest()
    case_id = manifest["cases"][0]["case_id"]
    checkpoint = {
        "run": {"provider": "synapse_garden", "model": "openai/gpt-6.1-sol",
                "limits": {"max_http_attempts": 6}},
        "paused": True,
        "pause_reason": "provider_error",
        "results": [
            {
                "case_id": case_id,
                "status": "paused_provider_error",
                "error": "Provider HTTP attempt budget exhausted",
            }
        ],
    }
    report = study.build_report(manifest, checkpoint)
    assert report["run"]["paused"] is True
    assert report["run"]["pause_reason"] == "provider_error"
    assert report["run"]["paused_case_errors"][0]["case_id"] == case_id
    assert report["run"]["paused_case_errors"][0]["error"].startswith("Provider HTTP attempt budget")
    markdown = study.report_markdown(report)
    assert "PAUSED (`provider_error`)" in markdown
    assert "Provider HTTP attempt budget exhausted" in markdown
    assert "`missing_result`" in markdown


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
        "shard_count",
    ):
        assert name in inputs, name
    assert inputs["execution_mode"]["default"] == "plan_only"
    assert (ROOT / ".github/workflows/recursive-gluing-eval.yml").read_text(encoding="utf-8") == text
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


# ---------------------------------------------------------------------------
# 11a. The pilot workflow's steps must actually run, in the order GitHub runs them
# ---------------------------------------------------------------------------


def _pilot_job_step(prefix: str) -> dict:
    job = _pilot_workflow()["jobs"]["evaluate"]
    return next(step for step in job["steps"] if (step.get("name") or "").startswith(prefix))


def _github_expressions(body: str) -> str:
    """Replace ``${{ github.x }}`` the way the runner does, for an offline run."""

    import re

    return re.sub(
        r"\$\{\{\s*github\.(\w+)\s*\}\}",
        lambda match: {"sha": "0" * 40, "run_id": "1", "actor": "local",
                       "workflow_ref": "local"}.get(match.group(1), "local"),
        body,
    )


def test_reasoning_pilot_steps_run_in_order_under_set_u(tmp_path: Path) -> None:
    """Run 40067626107 died in the Plan step with no plan and no artifact.

    The resolver exported `model=`/`wire_api=`/`key_env=` into ``$GITHUB_ENV``
    while the plan, gates and live steps read ``$MODEL``/``$WIRE_API``/``$KEY_ENV``.
    Under ``set -u`` the first unset read aborted the step, so the provider-free
    plan never ran and every later step was skipped. The YAML parsed, ``bash -n``
    passed, and each script looked correct on its own: only *running* the two
    steps in sequence exposes it. This test does that, with no provider call.
    """

    import os
    import subprocess

    workflow = _pilot_workflow()
    job = workflow["jobs"]["evaluate"]
    workdir = tmp_path / "repo"
    workdir.mkdir()
    # The plan step invokes `python tools/recursive_gluing_study.py`, so the
    # checkout must be reachable from the working directory.
    (workdir / "tools").symlink_to(ROOT / "tools", target_is_directory=True)
    for name in ("arena", "envs", "shared", "spec"):
        if (ROOT / name).is_dir():
            (workdir / name).symlink_to(ROOT / name, target_is_directory=True)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GITHUB_ACTIONS": "true",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "GITHUB_ENV": str(tmp_path / "env"),
        # The job-level `env:` block, with the two dispatch inputs resolved.
        "PROVIDER": "atria",
        "EXECUTION_MODE": "plan_only",
    }
    env.update({key: value for key, value in job["env"].items() if not str(value).startswith("${{")})
    (tmp_path / "env").write_text("", encoding="utf-8")
    (tmp_path / "summary.md").write_text("", encoding="utf-8")

    def run_step(step: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", _github_expressions(step["run"])],
            cwd=workdir, env=env, capture_output=True, text=True,
        )

    resolver = run_step(_pilot_job_step("Resolve the approved"))
    assert resolver.returncode == 0, resolver.stdout + resolver.stderr
    exported = dict(
        line.split("=", 1)
        for line in (tmp_path / "env").read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    # The exact variables the later steps dereference must be what was exported.
    for step_prefix in ("Plan (provider-free)", "Gates (provider-free)", "Live pilot"):
        step = _pilot_job_step(step_prefix)
        env_used = set(step.get("env") or {})
        for reference in ("MODEL", "WIRE_API", "REASONING_EFFORT", "API_BASE", "KEY_ENV"):
            script = step["run"]
            if f'"${reference}"' not in script and f"${{{reference}" not in script:
                continue
            if reference in env_used:
                continue  # supplied by the step's own env: block, not GITHUB_ENV
            assert reference in exported, (
                f"{step_prefix} reads ${reference} but the resolver exported {sorted(exported)}"
            )
    assert exported["MODEL"] == "Atria-Dawn-Preview"
    assert exported["WIRE_API"] == "responses"
    assert exported["REASONING_EFFORT"] == "high"
    assert exported["KEY_ENV"] == "ATRIA_API_KEY"
    assert exported["API_BASE"] == "https://api.atria-asi.ai/v1"

    env.update(exported)
    plan = run_step(_pilot_job_step("Plan (provider-free)"))
    assert plan.returncode == 0, plan.stdout + plan.stderr
    plan_json = workdir / "runs" / "recursive_gluing_pilot_plan" / "plan.json"
    assert plan_json.is_file(), "the plan step produced no plan.json: nothing would be uploaded"
    recorded = json.loads(plan_json.read_text(encoding="utf-8"))
    assert recorded["case_count"] == 2
    assert recorded["within_limits"] is True
    assert recorded["provider"] == "atria"
    assert recorded["model"] == "Atria-Dawn-Preview"
    assert recorded["wire_api"] == "responses"
    assert recorded["reasoning_effort"] == "high"
    assert recorded["limits"]["max_http_attempts"] == 192


# ---------------------------------------------------------------------------
# 11b. The reasoning pilot cannot be dispatched with a drifted configuration
# ---------------------------------------------------------------------------


def _pilot_workflow() -> dict:
    path = ROOT / "docs" / "workflows" / "recursive-gluing-reasoning-pilot.yml.example"
    assert path.is_file(), "the copyable pilot workflow must live in docs/workflows"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_reasoning_pilot_workflow_pins_the_frozen_slice_and_its_ceilings() -> None:
    """A pilot dispatch may choose the provider and whether to spend; nothing else.

    The first Atria/Mercury run is a bounded verification, not a campaign. If the
    ceilings or the case slice were inputs, one tired dispatch could turn it into
    an 18-case spend; if the model/wire/effort were typed, one typo could send
    Atria's reasoning effort down Chat Completions (where it has no effect) or
    Mercury's flat field down the Responses wire. Both are made unrepresentable:
    the two approved triples are derived from ``provider``, and every limit is a
    constant. This test is the contract, not a style check.
    """

    workflow = _pilot_workflow()
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"workflow_dispatch"}, "no schedule, no push, no self-dispatch"
    assert workflow["permissions"] == {"contents": "read"}

    inputs = triggers["workflow_dispatch"]["inputs"]
    # Exactly two dimensions: which provider, and whether to spend at all.
    assert set(inputs) == {"provider", "execution_mode"}
    assert set(inputs["provider"]["options"]) == {"atria", "mercury"}
    assert inputs["execution_mode"]["default"] == "plan_only"
    assert set(inputs["execution_mode"]["options"]) == {"plan_only", "live"}
    assert not [name for name in inputs if name.startswith("max_")], (
        "a ceiling must not be a dispatch input: this workflow may not raise one"
    )
    assert "model" not in inputs and "wire_api" not in inputs, (
        "model and wire API are derived from the provider so they cannot disagree"
    )

    job = workflow["jobs"]["evaluate"]
    env = job["env"]
    assert env["SCOPE"] == "diagnostic"
    assert env["SEEDS"] == "1"
    for name, value in {
        "MAX_API_CALLS": "48",
        "MAX_TOKENS_TOTAL": "49152",
        "MAX_WALL_SECONDS": "4800",
        "MAX_STEPS": "8",
        "MAX_TOKENS": "1024",
        "INVALID_RETRIES": "2",
    }.items():
        assert env[name] == value, f"{name} drifted from the frozen pilot ceiling"

    # The two approved triples, and only those, are produced by the resolver.
    resolver = next(step for step in job["steps"] if step.get("id") == "profile")
    script = resolver["run"]
    assert 'MODEL="Atria-Dawn-Preview"' in script
    assert "mercury-2.5" in script
    assert script.count('REASONING_EFFORT="high"') == 2
    assert script.count('WIRE_API="responses"') == 1
    assert script.count('WIRE_API="chat_completions"') == 1
    assert 'KEY_ENV="ATRIA_API_KEY"' in script
    assert 'KEY_ENV="INCEPTION_API_KEY"' in script

    # Those triples are exactly what the study accepts; a swapped pair is refused
    # provider-free, so the workflow cannot silently buy an uncontrolled run.
    case = {"case_id": "pilot", "environment": "recursive_gluing",
            "difficulty": "hard", "seed": 1}
    for provider, model, wire_api in (
        ("atria", "Atria-Dawn-Preview", "responses"),
        ("mercury", "mercury-2.5", "chat_completions"),
    ):
        plan = study.build_plan(
            [case], scope="diagnostic", matrix="diagnostic", seeds=[1],
            provider=provider, model=model, api_base=None, wire_api=wire_api,
            reasoning_effort="high", max_api_calls=48, max_tokens_total=49_152,
            max_wall_seconds=4_800, max_steps=8, max_tokens=1_024,
        )
        assert plan["within_limits"] is True
        assert plan["limits"]["max_http_attempts"] == 192
        with pytest.raises(study.StudyError):
            study.build_plan(
                [case], scope="diagnostic", matrix="diagnostic", seeds=[1],
                provider=provider, model=model, api_base=None,
                wire_api="chat_completions" if wire_api == "responses" else "responses",
                reasoning_effort="high", max_api_calls=48, max_tokens_total=49_152,
                max_wall_seconds=4_800, max_steps=8, max_tokens=1_024,
            )

    # A credential is never referenced from a shell step, and only the two
    # providers' names are exposed to the one step that needs them.
    for step in job["steps"]:
        assert "secrets." not in (step.get("run") or ""), step.get("name")
        assert "] && " not in (step.get("run") or ""), (
            f"{step.get('name')}: set -e would abort on an empty optional input"
        )
    live = next(step for step in job["steps"] if step.get("name", "").startswith("Live pilot"))
    assert live["if"] == "inputs.execution_mode == 'live'"
    assert set(live["env"]) == {"ATRIA_API_KEY", "INCEPTION_API_KEY", "MERCURY_API_KEY"}
    assert '--api-key-env "$KEY_ENV"' in live["run"]
    # No re-implementation of the harness, and no automatic retry of a paired call.
    for step in job["steps"]:
        script = step.get("run") or ""
        assert "tools/run_suite.py" not in script
        assert "env_runner" not in script
        assert "--auto" not in script

    import subprocess

    for step in job["steps"]:
        body = step.get("run")
        if not body:
            continue
        parsed = subprocess.run(["bash", "-n"], input=body, text=True, capture_output=True)
        assert parsed.returncode == 0, f"{step.get('name')}: {parsed.stderr}"

    note = (ROOT / "docs" / "workflows" / "recursive-gluing-eval.md").read_text(encoding="utf-8")
    assert "docs/workflows/recursive-gluing-reasoning-pilot.yml.example" in note
    assert ".github/workflows/recursive-gluing-reasoning-pilot.yml" in note


# ---------------------------------------------------------------------------
# 12. A pause names its own cause on the run page, not only in the artifact
# ---------------------------------------------------------------------------


def _paused_row(**overrides):
    row = {
        "case_id": "recursive_gluing__depth=hard__seed-0",
        "status": "paused_provider_error",
        "error": "provider or quota failure detected; resume only after checking the account",
        "failure_mode": "api_error",
        "elapsed_seconds": 71.0,
        "http_attempts": 4,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    row.update(overrides)
    return row


def _paused_checkpoint(*rows, **overrides):
    checkpoint = {
        "run": {"provider": "synapse_garden", "model": "openai/gpt-6.1-sol"},
        "paused": True,
        "pause_reason": "provider_error",
        "http_attempts_total": sum(int(row.get("http_attempts") or 0) for row in rows),
        "results": list(rows),
    }
    checkpoint.update(overrides)
    return checkpoint


def test_diagnosis_names_a_credential_rejection_and_redacts_the_secret() -> None:
    """Run 39586680263's pause was only readable inside the artifact zip.

    The diagnosis has to name the cause from the checkpoint and never print a
    credential back out, because annotations are public on the run page.
    """
    secret = "sk-live-abcdefghijklmnopqrstuvwxyz"
    checkpoint = _paused_checkpoint(
        _paused_row(
            stdout_tail=(
                "provider client: attempt 1 failed\n"
                f"ProviderError: HTTP 401 Invalid API Key! (key={secret})\n"
            )
        )
    )
    diagnosis = study.diagnose_pause(checkpoint)
    assert diagnosis["paused"] is True
    assert diagnosis["code"] == "credential_rejected"
    assert diagnosis["http_attempts_used"] == 4
    assert any("401" in item for item in diagnosis["evidence"])
    annotations = study.github_annotations(diagnosis)
    assert annotations and annotations[0].startswith("::error title=")
    assert "credential_rejected" in annotations[0]
    assert any(line.startswith("::notice title=") for line in annotations)
    rendered = "\n".join(annotations) + "\n" + study.diagnosis_markdown(diagnosis)
    assert secret not in rendered
    assert "[REDACTED]" in rendered
    for line in annotations:
        assert "\n" not in line
        assert len(line) <= study.ANNOTATION_MESSAGE_LIMIT + 200


def test_diagnosis_names_the_physical_budget_before_generic_provider_error() -> None:
    checkpoint = _paused_checkpoint(
        _paused_row(status="paused_provider_error", stderr_tail="Provider HTTP attempt budget exhausted\n")
    )
    diagnosis = study.diagnose_pause(checkpoint)
    assert diagnosis["code"] == "http_attempt_budget"
    assert "budget" in diagnosis["cause"]


def test_diagnosis_does_not_invent_a_cause_it_cannot_read() -> None:
    checkpoint = _paused_checkpoint(_paused_row(stdout_tail="something entirely unexpected\n"))
    diagnosis = study.diagnose_pause(checkpoint)
    assert diagnosis["code"] == "provider_error_unclassified"
    assert "does not name" in diagnosis["next_step"] or "does not name" in diagnosis["headline"]


def test_diagnosis_of_a_completed_leg_is_not_a_pause() -> None:
    diagnosis = study.diagnose_pause({"paused": False, "results": []}, manifest={"cases": [{}]})
    assert diagnosis["paused"] is False
    assert diagnosis["code"] == "complete"
    assert study.github_annotations(diagnosis) == []


def test_diagnosis_of_a_refused_dispatch_names_the_credential_path() -> None:
    """Exit 2 is the study's own refusal (usually a missing secret): no checkpoint."""
    diagnosis = study.diagnose_pause(None, manifest={"cases": [{}] * 18}, exit_status=2)
    assert diagnosis["code"] == "no_checkpoint"
    assert "provider secret" in diagnosis["cause"]
    assert diagnosis["planned_case_count"] == 18
    annotations = study.github_annotations(diagnosis)
    assert annotations[0].startswith("::error title=")


def test_diagnosis_of_a_floor_effect_pause_is_a_warning_not_a_failure() -> None:
    checkpoint = _paused_checkpoint(
        _paused_row(status="scored", error=None, verdict="FAIL", score=0.0),
        pause_reason="floor_effect",
        floor_effect=True,
    )
    diagnosis = study.diagnose_pause(checkpoint)
    assert diagnosis["code"] == "floor_effect"
    assert study.github_annotations(diagnosis)[0].startswith("::warning title=")


def test_report_prints_the_pause_diagnosis(tmp_path: Path) -> None:
    manifest, _plan = _manifest()
    case_id = manifest["cases"][0]["case_id"]
    checkpoint = _paused_checkpoint(
        _paused_row(case_id=case_id, stderr_tail="HTTP 429 Too Many Requests\n")
    )
    report = study.build_report(manifest, checkpoint)
    assert report["run"]["pause_diagnosis"]["code"] == "rate_limited"
    markdown = study.report_markdown(report)
    assert "Pause diagnosis: `rate_limited`" in markdown
    assert "Provider rate limited" in markdown or "rate limited" in markdown
    assert "Next step:" in markdown


def test_diagnose_command_is_provider_free_and_never_masks_the_leg(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "suite_checkpoint.json").write_text(
        json.dumps(
            _paused_checkpoint(
                _paused_row(stderr_tail="Provider HTTP attempt budget exhausted\n")
            )
        ),
        encoding="utf-8",
    )
    status = study.main(
        [
            "diagnose",
            "--run-out",
            str(run_dir),
            "--exit-status",
            "3",
            "--github",
            "--out",
            str(tmp_path / "pause.json"),
        ]
    )
    # A diagnosis reports the failure; it must never become one and mask the
    # controller's exit status in the caller.
    assert status == 0
    printed = capsys.readouterr().out
    assert "::error title=" in printed
    assert "http_attempt_budget" in printed
    assert "## Pause diagnosis: `http_attempt_budget`" in printed
    written = json.loads((tmp_path / "pause.json").read_text(encoding="utf-8"))
    assert written["code"] == "http_attempt_budget"


def test_the_run_command_carries_its_pause_onto_the_run_page(monkeypatch, capsys) -> None:
    """The runner parses a child process's stdout, so no workflow edit is needed.

    This session's GitHub App cannot write `.github/workflows/**` (see
    `docs/audits/2026-10-20-workflow-token-repair.md`), so the annotation has to
    come from the study command itself.
    """
    diagnosis = study.diagnose_pause(
        _paused_checkpoint(_paused_row(stderr_tail="HTTP 429 Too Many Requests\n"))
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert study.emit_pause_annotations(diagnosis) is False
    assert capsys.readouterr().out == "", "a CLI or a test must never see workflow commands"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert study.emit_pause_annotations(diagnosis) is True
    printed = capsys.readouterr().out
    assert printed.startswith("::error title=")
    assert "rate_limited" in printed


def test_a_refused_dispatch_is_annotated_inside_actions(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    status = study.main(
        [
            "run",
            "--manifest",
            str(manifest),
            "--out",
            str(tmp_path / "out"),
            "--execution-mode",
            "gates_only",
            "--provider",
            "synapse_garden",
            "--model",
            "openai/gpt-6.1-sol",
        ]
    )
    assert status == 2
    captured = capsys.readouterr()
    assert "::error title=Recursive gluing study refused the dispatch::" in captured.out
    assert "no study block" in captured.err
