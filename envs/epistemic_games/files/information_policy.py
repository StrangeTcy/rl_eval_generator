"""Declared evidence-selection policy for epistemic_games (decision item 5).

This module is the falsifiable form of the "Announcement policy (common
knowledge)" prose in task.md.  It follows the renderer-hook contract:

- ``select(context)`` is a pure function of the seeded substitutions; the
  generator bakes its output as the POLICY_ID / POLICY_RECORD placeholders
  in judge.py.  This file deliberately contains no placeholder markers of
  its own: staging resolves markers in every text file it copies, and this
  module ships byte-identical to the checkout source the manifest pins - so
  what the judge ran is exactly what ``verify_manifest`` can re-hash;
- this same file ships to the judge (layout ``judge/information_policy.py``);
- the judge re-runs ``replay(rebuilt_spec)`` and compares against the baked
  record; a mismatch is ``reward_denial`` (the INSTANCE_SPEC-rebuild
  precedent).

Honesty note: v1 is a *constant* declaration - one public announcement,
always delivered, world 2 a level-3 (reader-dependent) speaker, the signal
table drawn from ``core.EVIDENCE_TABLE``.  It does not yet vary across
instances; what it does is make the selection process re-derivable, which is
the admissibility condition for this family's type-3 deception claim
("the transcript was strategically chosen").  PR-D's publicity/delivery axes
(P2.1) turn these constants into parameters, and this module is where their
values get recorded and checked.
"""
from __future__ import annotations

import ast
from fractions import Fraction

import core

POLICY_ID = "epistemic_announcement_v1"


def _exact(value: float) -> Fraction:
    """Recover the exact table Fraction behind a spec float.

    Every probability in ``core.EVIDENCE_TABLE`` has an exact short-decimal
    value, so ``str()``'s shortest round-trip representation recovers it
    without binary-float noise.  The judge-side comparison is then exact,
    like the engine's own Fraction arithmetic.
    """
    return Fraction(str(value))


def _record(spec: dict) -> dict:
    """The falsifiable claim this policy makes about one baked instance spec.

    Every field is *recomputed* - from the spec's tables through ``core``'s
    declared machinery - never echoed from prose.  Key order is fixed at
    source level so ``repr()`` is a canonical, comparable literal on both
    sides of the generation/judge boundary.
    """
    hypotheses = spec["hypotheses"]
    hyp1 = hypotheses[core.WORLD1]
    hyp2 = hypotheses[core.WORLD2]
    likelihoods = spec["likelihoods"]

    # Band: recompute the verdict through the shared exact-semantics substrate
    # (single source of truth for the likelihood-ratio band, per the
    # branch-integration reconciliation - core.py now delegates here too).
    # Accessed via ``core._semantics_bayes`` because this module's own purity
    # contract (shared/information_policy.py) forbids importing sys/pathlib,
    # which a direct three-context import fallback would require; core is an
    # allowed sibling import and already binds the shared package.
    l1 = _exact(likelihoods[core.WORLD1])
    l2 = _exact(likelihoods[core.WORLD2])
    _, expected_verdict = core._semantics_bayes.likelihood_ratio_band(l1, l2)

    # Signal policy: the two behavior tables must be one of the declared
    # (honest_evasion, strategic_denial) draws for this evidence level.
    honest_evasion = _exact(hyp1["behavior"]["vague"])
    strategic_denial = _exact(hyp2["behavior"]["denial"])
    drawn = any(
        he == honest_evasion and sd == strategic_denial
        for he, sd in core.EVIDENCE_TABLE[spec["evidence"]]
    )

    # Reader dependence: recompute the level-1 action and the level-3 best
    # response to a level-1 reader; the mimicry invariant (type-3 strategic
    # selection) must hold on the rebuilt spec, not on the spec's prose.
    level1_action = core.level1_action(hyp1["internal_state"])
    level3_best = core.level3_action(
        hyp2["internal_state"], target_state=hyp1["internal_state"]
    )

    return {
        "band": {
            "likelihood_ratio": spec["likelihood_ratio"],
            "verdict": spec["verdict"],
            "verdict_matches_band": expected_verdict == spec["verdict"],
        },
        "channel": {
            "acknowledged": False,
            "announcements": 1,
            "delivery": "always",
            "publicity": "public",
        },
        "policy_id": POLICY_ID,
        "reader_dependence": {
            "level1_action": level1_action,
            "level3_best_response": level3_best,
            "mimicry_holds": level1_action == level3_best,
            "world2_goal": hyp2["goal"],
            "world2_level": hyp2["level"],
        },
        "signal_policy": {
            "drawn_from_declared_table": drawn,
            "evidence_level": spec["evidence"],
            "honest_evasion": float(honest_evasion),
            "strategic_denial": float(strategic_denial),
        },
        "support": {
            "min_likelihood_positive": min(_exact(v) for v in likelihoods.values()) > 0,
            "observation": spec["observation"],
        },
    }


def select(context: dict) -> dict:
    """Generator-side entry (renderer-hook contract).

    Pure function of the seeded substitutions: parse the baked instance spec
    the renderer just produced and return the policy placeholders.  The
    record is baked as a Python literal (``repr``) and the judge compares
    ``replay()``'s dict against it by exact literal equality.
    """
    spec = ast.literal_eval(context["subs"]["JUDGE_INSTANCE"])
    return {
        "POLICY_ID": POLICY_ID,
        "POLICY_RECORD": repr(_record(spec)),
    }


def replay(spec: dict) -> dict:
    """Judge-side entry: recompute the record from the *rebuilt* spec.

    Returns the same dict ``select`` baked as ``POLICY_RECORD_BAKED`` (a
    Python literal in judge.py), so the judge's check is an exact literal
    equality: floats round-trip through ``repr`` without noise and dict
    equality does not depend on key order.  Same module, same function, both
    sides of the boundary: one source of truth.
    """
    return _record(spec)
