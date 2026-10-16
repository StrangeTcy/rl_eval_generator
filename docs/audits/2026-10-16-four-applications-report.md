# Four recursive-gluing applications — report

Date: 2026-10-16.
Branch: `arena/1ddc930c-rl-eval-generator`.

## 1. State

| | |
|---|---|
| Starting local HEAD | `8736607` with untracked copies of origin; ff-only merge after `stash -u` |
| Starting origin / work HEAD | `aa1bc82be57c0d44c6fbda108371d912587f358b` (clean) |
| Ending HEAD | this commit |
| Stash | dropped after ff; it only duplicated origin |

No reset, rebase, force-push, paid APIs, or model campaigns.

## 2. Files

Four sibling envs under `envs/cat_theo/`, each with `config.yaml` and
`files/{network,judge,prompt,solver,visible_tests}.py`. Tests:
`tests/test_recursive_{holonomy_gluing,compiler_bootstrap,error_correcting_codes,coarse_graining}.py`.
Registry, README, `test_cat_theo.py`. Notes in `docs/audits/` and
`docs/decisions/2026-10-16-four-recursive-applications.md`.

Existing maze/distributed/epistemic/v0/discovery files were not modified.

## 3. Semantics and verifiers

**Holonomy.** Compose finite maps (mul on \(\mathbb F_7^\times\), affine on
\(\mathbb F_7\), permutations on 4 points). SAT iff the composite has a
returning state. Judge enumerates the domain; inferred SAT must match
calibration. `[formal]` `[tested]`

**Compiler.** `eval_source` vs `eval_bytecode` on a finite program set after
compile+encode+claimed decode. Local encodings can all be correct while the
path decoder is not. `[tested]`

**Codes.** \(H=[1\,1]\) over \(\mathbb F_5\), glues, parent parity. Oracle:
field matvec + enumerate assignments. `[tested]`

**Coarse-graining.** Integer \(T[L,R]=\sum_s W[L,s,R]\); series
\(T_{12}[L,R]=\sum_m T_1[L,m]T_2[m,R]\). `fixed` iff `compose(T,T)=T`. `[tested]`

## 4. Worked examples `[tested]`

- Holonomy mul REC_COMP: composite \(q=3\neq1\), no returning state; identity
  children each have returning states.
- Compiler REC_COMP: each stage locally ok; claimed decoder disagrees on `0`.
- Codes REC_COMP: local kernels nonempty; stacked system unsat (parent rhs=1).
- Coarse REC_COMP: series of all-ones weights → table `[[8,8],[8,8]]`, not a
  doubling fixed point. DIRECT projector `[[1,0],[0,0]]` is a fixed point.

## 5. Controls

Implemented A/B/C/D as `direct` / `recursive` / `flat` / `recursive_composition`.
Revealed vs inferred representation. Explicit expansion is a holonomy grade
item (`expanded`) and a codes revealed-perm item. Deferred: world-dependent
inner frames, DEL, nontrivial generator matrices beyond \(H=[1\,1]\),
floating-point physics.

## 6. Tests

```
.venv/bin/python -m pytest tests/test_recursive_holonomy_gluing.py \
  tests/test_recursive_compiler_bootstrap.py \
  tests/test_recursive_error_correcting_codes.py \
  tests/test_recursive_coarse_graining.py \
  tests/test_recursive_maze_gluing.py tests/test_recursive_distributed_gluing.py \
  tests/test_recursive_epistemic_gluing.py tests/test_recursive_gluing.py \
  tests/test_recursive_gluing_discovery.py tests/test_experiment_arms.py \
  tests/test_latent_registry.py -q
```

**136 passed, 0 skipped.**

## 7. Compact vs expanded

`docs/audits/2026-10-16-four-apps-scaling.json`. Holonomy public ~350 bytes;
expanded map count is `depth+1` on REC_COMP (depth 1 is lifted to 2). Codes
public ~470 bytes; enumerator size \(5^6=15625\) and does **not** grow with
the depth axis (limitation).

## 8. Baselines `[tested]`

Held-out seeds `10000+`. Local-only / “trust the claim” / first-region table
baselines have UNSAT/non-fixed accuracy **0** on the D-class instances.
Reference solver accuracy **1**. JSON under `docs/audits/2026-10-16-*-baselines.json`.

## 9. Limitations

- Codes depth axis does not add symbols; obstruction is the 3-block system.
- Holonomy REC_COMP forces depth ≥ 2.
- Compiler program set is six hand-listed expressions, not all ASTs of a given height.
- Coarse-graining is a 2-spin integer toy, not a lattice model in the continuum.
- Directory `recursive_holonomy_gluing` leaks `holonomy`; rendered prompts do not.
- No model has been run.

## 10. Claims ledger

| Claim | Tag |
|---|---|
| Four distinct oracles (maps / interpreters / F_p / integer tables) | `[tested]` |
| Mul returning-state iff Q=1 on F_p^x | `[formal]` `[tested]` |
| Affine translation has no returning state; 2x+1 has one | `[formal]` `[tested]` |
| Local compiler stages ok while path decoder fails | `[tested]` |
| Local code kernels nonempty, stacked unsat | `[tested]` |
| Projector table is a doubling fixed point; all-ones series is not | `[tested]` |
| Existing five recursive families unchanged | `[tested]` |
| Models recover latent maps/encodings/codes/tables | `[requires model runs — not done]` |
