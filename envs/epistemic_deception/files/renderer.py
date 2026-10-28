from __future__ import annotations
import pprint
from typing import Dict
import core


def render(subs: Dict[str, str]) -> Dict[str, str]:
    instance = core.build_instance(subs["MODE_ID"], subs["MECHANISM_ID"], subs["INCENTIVE_ID"],
                                   subs["VISIBILITY_ID"], subs["SCENARIO_ID"], int(subs["SEED"]))
    return {"TASK_MD": instance.task(), "JUDGE_INSTANCE": pprint.pformat(instance.to_spec(), indent=4, width=100, sort_dicts=False)}
