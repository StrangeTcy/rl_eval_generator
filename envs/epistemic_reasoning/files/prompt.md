# Epistemic reasoning: %%VARIANT_TITLE%%

This is a deterministic, direct-answer task over a finite model. All learner-visible inputs are in `task.json`; judge-only oracle data is not included in the agent workspace.

%%TASK_MD%%

## Submission format

Edit only `answer.py`. Keep it as one Python literal assignment, `ANSWER = {...}`; do not add imports, functions, or code. The variant-specific answer fields are prefilled as a schema-shaped starter. Posterior probabilities must be reduced exact rational strings, never floats. Run `python visible_tests.py`, then submit with `python /tools/submit.py`.
