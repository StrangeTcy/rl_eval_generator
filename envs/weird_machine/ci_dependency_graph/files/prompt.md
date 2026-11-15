# CI Dependency Graph Execution Evaluation Environment

You are tasked with implementing a CI workflow execution graph generator in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`).

## Problem Statement

Continuous Integration (CI) configuration workflows (such as YAML pipelines) are executable directed acyclic graphs (DAGs). The dependency specification (`needs`) and stage variables encode topological execution scheduling.

You are given `dependencies`, mapping arbitrary positive integer job IDs to finite sequences of upstream job IDs that must finish before the job can start. Job IDs and mapping insertion order are unrelated to topological order. A graph may have multiple roots and disconnected components.

Your task is to implement `generate_workflow` inside `%%MODEL_CLASS%%`. The method must return a workflow mapping each supplied ID `i` to the job name `"job_{i}"` and its job specification.

### Specification Requirements
Each job specification dictionary `workflow["job_{i}"]` must contain:
1. `"needs"`: A sequence of string job names corresponding exactly to the upstream dependencies of job $i$ (e.g., `("job_1", "job_2")`). If job $i$ has no dependencies, `"needs"` should be empty.
2. `"env"`: A dictionary containing key `"LAYER"`, whose integer value represents the topological depth of the job in the DAG:
   - For root jobs (no dependencies), `LAYER` must be `0`.
   - For downstream jobs, `LAYER` must equal $\max(\text{LAYER of upstream dependencies}) + 1$.

## Requirements
1. Implement `generate_workflow` inside `%%MODEL_CLASS%%`.
2. Ensure the returned workflow dictionary matches all dependencies accurately and correctly propagates layer depth across arbitrary DAG structures.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
