# Four application environments under the recursive-gluing umbrella

Date: 2026-10-16.

Existing maze / distributed / epistemic / v0 / discovery families are unchanged.
These four siblings share generator/judge scaffolding only.

## Holonomy (`recursive_holonomy_gluing`)

Finite maps on nested modules. Families: multiplication on \(\mathbb F_p^\times\),
affine maps on \(\mathbb F_p\), listed permutations. Parent map = composition of
children. Compatible state: a domain element fixed by the composite, first map
first. Unrestricted point-assignments glue; empty fixed-state set is an empty
constrained solution set, not a failed sheaf axiom.

Candidate prompt does not use the words holonomy, sheaf, or logarithm.
The directory name does.

## Compiler (`recursive_compiler_bootstrap`)

Source `add`/integers and push/add/halt bytecode, both modulo 5. Oracle
*executes* programs. Local stage contracts hold under each stage's own
encoding. A bootstrap claim names a decoder for the last encoding; it can
fail observational equivalence without any stage being locally wrong.

## Codes (`recursive_error_correcting_codes`)

Length-2 blocks over \(\mathbb F_5\) with \(H=[1\,1]\). Glues identify
coordinates; a parent parity may make the stacked system empty while every
local kernel is nonempty. Oracle is matrix-vector arithmetic plus enumeration
of \(5^{6}\) or fewer assignments.

## Coarse-graining (`recursive_coarse_graining`)

Two-state spins, nonnegative integer weights. Effective table by exact sum;
series composition by exact sum-product. Doubling fixed point is equality of
`compose(T,T)` with `T`. Not a CSP.

## Controls

| Code | Holonomy | Compiler | Codes | Coarse |
|---|---|---|---|---|
| A direct | identity map | one compile | one block | one region |
| B recursive | nested, still has a returning state | compile+recode, matching decoder | glued, rhs=0 | series of projectors |
| C flat | three-map cycle, no nesting | two-stage without extra nesting | three blocks, rhs=0 | one non-fp region |
| D recursive composition | nested identity children + twist with no returning state | matching local encodings, wrong path decoder | glued + parent rhs=1 | series of all-ones weights |

Representation: revealed vs inferred (calibration only). Explicit expansion
is a holonomy/codes grade item (`expanded` maps / revealed perms).

Presentation twins: family-preserving coordinate change; opcode-id
permutation; symbol-scale meta; spin-label swap.
