# Recursive gluing design validation

Date: 2026-10-26  
Design: `docs/decisions/2026-10-26-recursive-gluing-experimental-design.json`

The design was subsequently source-audited against all nine family members. That
audit is documented in the design artifact itself; this report's static artifact
validation predates that audit and was not rerun under the current no-execution
constraint.

## Executed checks

| check | command | result |
|---|---|---|
| independent manifest/static validation | Node.js validation of counts, exact case-id recomputation, eight config paths, eight oracle files, holonomy exclusion, readiness caveats, family condition contracts, and call arithmetic | **15/15 passed** |
| JSON syntax and accounting | `node -e "require('./docs/decisions/2026-10-26-recursive-gluing-experimental-design.json')"` | **passed**; 18 diagnostic episodes / 160 hidden checks / 1296 logical calls; 24 family episodes / 183 hidden checks / 1728 logical calls |
| patch whitespace | `git diff --check` | **passed** |

The earlier independent validation output is saved at
`runs/recursive_gluing_design/static_manifest_validation.json`.

## Blocked checks

The repository's provider-free Python checks could not start in this worker:

```text
$ python -m pytest tests/test_recursive_gluing_study.py tests/test_recursive_apps_readiness.py -q
Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.
Exited with code 49

$ python -m compileall -q tools/recursive_gluing_study.py tools/recursive_references.py ...
Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.
Exited with code 49
```

Therefore the repository's reference/gate/scoring tests are **not reported as
passing**. No external model call, provider preflight, Docker episode, or live
score was executed. Once Python 3.11+ and the project dependencies are exposed,
the next checks are:

```bash
python -m pytest tests/test_recursive_gluing_study.py tests/test_recursive_apps_readiness.py -q
python -m pytest -q
python tools/recursive_gluing_study.py plan --scope diagnostic --seeds 0,1 ...
python tools/recursive_gluing_study.py plan --scope family --matrix diagnostic --seeds 0 ...
```

The two plan commands should be run with the exact provider/model and ceilings
recorded in the manifest before any live dispatch is considered.
