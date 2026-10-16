# Audit: four recursive-gluing application environments

Date: 2026-10-16.

## Repository state before edits

```
git status --short     (clean after ff-only merge)
git branch --show-current
arena/1ddc930c-rl-eval-generator
git rev-parse HEAD
aa1bc82be57c0d44c6fbda108371d912587f358b
git log --oneline -8
aa1bc82 fix epistemic bool coercion and maze exhausted-depth replay
a15d2d9 separate pairwise, deep, and nested obstructions in epistemic gluing
3a87f78 audit necessity of recursive gluing on the three domain families
d365d9e add maze, distributed, and epistemic recursive gluing families
c50f128 measure compact vs expanded recursive gluing and audit the claims
ee095ed rewrite recursive_gluing_discovery as a compact recursive grammar
9f6ba2f add recursive_gluing_discovery as the v0 control's research sibling
93cc8dc add recursive_gluing environment
git stash list
(empty after dropping a stash that only duplicated origin)
```

Local HEAD had been `8736607` with untracked copies of origin. Preserved via
`git stash -u` then `git merge --ff-only origin/arena/1ddc930c-rl-eval-generator`.
No reset, rebase, or force-push.

## Conventions reused

- Registry: `envs/registry.yaml`
- Layout: `config.yaml` axes + `files/{prompt.md,solver.py,visible_tests.py,judge.py,network.py}`
- Judge scaffolding: generate public instances, run candidate twice, `verify_certificate`
- Budget: `OracleBudgetExceeded` → `judge_runtime_error`, never UNSAT
- No `shared.experiment_arms`
- Existing families kept byte-for-byte:
  `recursive_gluing`, `recursive_gluing_discovery`,
  `recursive_maze_gluing`, `recursive_distributed_gluing`,
  `recursive_epistemic_gluing`

## Names to register (no collisions)

- `recursive_holonomy_gluing`
- `recursive_compiler_bootstrap`
- `recursive_error_correcting_codes`
- `recursive_coarse_graining`

Directory `recursive_holonomy_gluing` contains the stem `holonomy`; candidate
prompts will not.

## Semantic split (not one CSP)

| Env | Native object | Oracle | Witness |
|---|---|---|---|
| holonomy | finite maps (mul / affine / perm) on a cycle of modules | compose maps; enumerate fixed states | port states + inferred maps |
| compiler | source AST + bytecode + encodings | run interpreters | encodings + a disagreeing program if any |
| codes | F_p vectors + parity-check matrices | matrix-vector products | block codewords |
| coarse-graining | integer spin weights | exact sum-product of tables | effective boundary table |
