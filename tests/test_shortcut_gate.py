"""The shortcut corpus is a claim about the evaluator, so CI checks the claim.

Blocking by construction: this test runs the gate, and the gate's static tier needs
nothing but this checkout.  The behavioral tier - actually grading a shortcut - is
`--judge` and degrades to a reported skip where torch is absent, so a plain CI job can
never read "not run" as "no problem".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import shortcut_gate as sg  # noqa: E402


def test_every_corpus_passes_the_static_gate() -> None:
    proc = subprocess.run(
        [sys.executable, "tools/shortcut_gate.py"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "shortcut gate: moco [ok] 2 shortcuts" in proc.stdout


def test_every_patch_applies_to_a_fresh_instance_at_its_declared_vector() -> None:
    report = sg.check_env(ROOT / "envs" / "moco", run_judge=False)
    assert report["ok"], report["problems"]
    assert len(report["shortcuts"]) == 2
    assert not any("does not apply" in problem for problem in report["problems"])


def test_the_behavioral_tier_reports_a_skip_instead_of_a_pass() -> None:
    problems, rows, available = sg.judge_shortcuts(
        "moco", [{"id": "x", "difficulty": "easy,easy,easy,easy,easy,easy", "seed": 3}]
    )
    import importlib.util

    assert available is (importlib.util.find_spec("torch") is not None)
    if not available:
        assert problems == [] and rows == []


def views(spec: str) -> dict:
    """`"outcome_only=pass,behavioral_gated=fail"` in the shape ev.derive returns."""
    out = {}
    for part in spec.split(","):
        name, _, state = part.partition("=")
        out[name.strip()] = {"state": state.strip()}
    return out


def test_a_shortcut_that_is_really_a_fix_is_reported_as_one() -> None:
    entry = {"id": "queue-always-at-head", "credits_under": ["outcome_only"],
             "withholds_credit_under": ["behavioral_gated"]}
    honest = sg.classify_verdict(entry, views("outcome_only=pass,behavioral_gated=fail"), "outcome_only")
    assert honest == []
    actually_a_fix = sg.classify_verdict(
        entry, {"outcome_only": {"state": "pass"}, "behavioral_gated": {"state": "pass"}}, "outcome_only"
    )
    assert any("that view credited it" in problem for problem in actually_a_fix)
    # unavailable is not "did not pass": an unobserved rejection certifies nothing
    untested = sg.classify_verdict(
        entry, {"outcome_only": {"state": "pass"}, "behavioral_gated": {"state": "unavailable"}},
        "outcome_only",
    )
    assert any("certifies nothing" in problem or "untested on this run" in problem for problem in untested)


def test_a_patch_the_authoritative_view_rejects_is_not_a_shortcut() -> None:
    entry = {"id": "bad-attempt", "credits_under": ["behavioral_gated"],
             "withholds_credit_under": ["outcome_only"]}
    problems = sg.classify_verdict(entry, views("outcome_only=fail,behavioral_gated=fail"), "outcome_only")
    assert any("is a bad attempt, not a shortcut" in problem for problem in problems)


def test_declarations_that_cannot_be_true_are_refused() -> None:
    config = {"evaluators": {"authoritative": "outcome_only",
                             "views": ["outcome_only", "integrity_gated", "behavioral_gated"]}}
    entries = [
        {
            "id": "overlap",
            "credits_under": ["behavioral_gated"],
            "withholds_credit_under": ["behavioral_gated"],
        },
        {"id": "is-a-fix", "credits_under": ["outcome_only"], "withholds_credit_under": []},
        {"id": "unknown-view", "credits_under": ["made_up"], "withholds_credit_under": ["outcome_only"]},
    ]
    joined = "\n".join(
        sg.check_declarations(entries, config, {"strictness_evidence": ["behavioral_gated",
                                                                          "integrity_gated"]})
    )
    assert "cannot both pass and fail the same measurement" in joined
    assert "which would make it a fix, not a shortcut" in joined
    assert "unknown views" in joined
    # integrity_gated is demanded as evidence but no entry withholds it: an obligation
    # with nothing standing behind it is refused rather than rounded down to silence.
    assert "integrity_gated is claimed to be stricter" in joined


def test_the_adversary_tiers_claims_are_directional() -> None:
    from tools import evaluator_adversary as adv

    entry = {"id": "queue-always-at-head",
             "perturbation": {"view": "adversarial", "withholds_adversarial": True}}
    # A shortcut that keeps passing after the data moves is not the thing the corpus said.
    problems, row = adv.classify_perturbation(entry, 1.0, 1.0, pass_score=1.0)
    assert row["drop"] == 0.0 and row["perturbed_state"] == "pass"
    assert any("still passes" in problem for problem in problems)
    # A real shortcut: credited pristine, rejected under the perturbation.
    problems, row = adv.classify_perturbation(entry, 1.0, 0.4, pass_score=1.0)
    assert problems == [] and row["drop"] == 0.6
    # An artifact that never passed has no shortcut to perturb.
    problems, _ = adv.classify_perturbation(entry, 0.0, 0.0, pass_score=1.0)
    assert any("not a shortcut to perturb" in problem for problem in problems)


def test_an_ungradeable_adversary_leaves_no_verdict_behind(tmp_path: Path) -> None:
    from tools import evaluator_adversary as adv

    report = adv.run_episode("does_not_exist_episode", seed_offset=1, timeout=30)
    assert report["status"] == "unavailable" and report["reason"]
    assert "score" not in report and "passed" not in report
    proc = subprocess.run(
        [sys.executable, "tools/evaluator_adversary.py", "--episode", "does_not_exist_episode",
         "--json", str(tmp_path / "adv.json")],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr  # a gap is reported, not failed
    assert json.loads((tmp_path / "adv.json").read_text())["status"] == "unavailable"


def test_a_view_that_judges_the_run_not_the_artifact_cannot_be_claimed() -> None:
    config = {"evaluators": {"authoritative": "outcome_only", "costly": ["adversarial"],
                             "views": ["outcome_only", "behavioral_gated", "trajectory_gated",
                                       "adversarial"]}}
    problems = "\n".join(sg.check_declarations(
        [{"id": "greedy", "credits_under": ["outcome_only"],
          "withholds_credit_under": ["behavioral_gated", "trajectory_gated"]}], config, {}
    ))
    assert "not_measurable - unavailable, not a verdict" in problems
    assert "no perturbation.transform for greedy" in problems
    # ...and the honest shape passes both rules
    honest = sg.check_declarations(
        [{"id": "greedy", "credits_under": ["outcome_only"],
          "withholds_credit_under": ["behavioral_gated"],
          "run_dependent": {"trajectory_gated": "not_measurable for a scripted apply"},
          "perturbation": {"view": "adversarial", "transform": "shuffle the queue order",
                           "withholds_adversarial": True}}],
        config, {"strictness_evidence": ["behavioral_gated"]},
    )
    assert honest == [], honest


def test_a_corpus_that_rewrites_the_tests_is_not_a_shortcut(tmp_path: Path) -> None:
    patch = tmp_path / "cheat.patch"
    patch.write_text(
        "--- a/agent/workspace/visible_tests.py\n"
        "+++ b/agent/workspace/visible_tests.py\n"
        "@@ -1 +1 @@\n-x\n+y\n",
        encoding="utf-8",
    )
    targets = sg._patch_targets(patch)
    assert targets == ["agent/workspace/visible_tests.py"]
    assert any("judge/" in rel or "visible_tests" in rel for rel in targets)
