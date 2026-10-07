"""Seeded renderer for the epistemic_reasoning family."""

from __future__ import annotations

import json
import pprint

import task_engine


def render(subs: dict[str, str]) -> dict[str, str]:
    """Bake public task data and a separate judge-side oracle specification."""
    variant = subs["VARIANT"]
    size = subs["SIZE"]
    seed = int(subs["SEED"])
    instance = task_engine.build_instance(variant, size, seed)
    public = instance["public"]
    answer_starter = task_engine.answer_template(variant, public)
    public_json = json.dumps(public, indent=2, ensure_ascii=False, sort_keys=False)
    return {
        "TASK_MD": task_engine.answer_guide(variant, public),
        "PUBLIC_TASK_JSON": public_json,
        "ANSWER_TEMPLATE": pprint.pformat(answer_starter, indent=4, width=88, sort_dicts=True),
        "JUDGE_INSTANCE": pprint.pformat(instance, indent=4, width=100, sort_dicts=True),
        "VARIANT_TITLE": task_engine.VARIANT_TITLES[variant],
    }
