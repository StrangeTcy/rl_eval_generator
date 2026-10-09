"""Renderer hook for generate_env.py (epistemic_silence family).

Opt-in deterministic renderer: ``render(subs)`` receives the placeholder
table built from the axis levels (plus SEED / JUDGE_SEED / scoring values)
and returns extra placeholder values. It must be a pure function of ``subs``
- seeded randomness only - because its output is baked into generated
instances and re-derived by the judge.

Bakes two values:
  TASK_MD         the agent-facing task (public information only)
  JUDGE_INSTANCE  the judge-side instance spec as a Python literal
                  (full latent game + ground truth + provenance)
"""
from __future__ import annotations

import pprint
from typing import Dict

import core


def render(subs: Dict[str, str]) -> Dict[str, str]:
    seed = int(subs["SEED"])
    instance = core.build_instance(
        observation=subs["OBSERVATION_ID"],
        protocol=subs["PROTOCOL_ID"],
        prior=subs["PRIOR_ID"],
        scenario=subs["SCENARIO_ID"],
        seed=seed,
    )
    spec = instance.to_spec()
    return {
        "TASK_MD": instance.public_task_md(),
        "JUDGE_INSTANCE": pprint.pformat(spec, indent=4, width=100, sort_dicts=False),
    }
