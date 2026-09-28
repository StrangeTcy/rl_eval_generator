"""Baked instance specification for the judge (auto-generated).

This file is produced by the environment renderer and lives only in the
judge image/workspace - it is NOT part of the agent workspace. The judge
rebuilds the instance from (template, evidence, prior, presentation, seed)
using core.py and requires the rebuilt specification to match INSTANCE_SPEC
exactly. Any mismatch means the instance lost provenance and the
submission is graded as reward_denial.
"""

INSTANCE_SPEC = %%JUDGE_INSTANCE%%
