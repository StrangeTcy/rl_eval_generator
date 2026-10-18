# Compositional reasoning experiments — scientific-design audit

Date: 2026-10-18.
Branch: `arena/1ddc930c-rl-eval-generator`.
HEAD inspected: `0dcb51cbfa35598fa843905c3384d93a5fc95a71`.

This is a design review of existing artifacts. No environment was changed,
no test was added, and no model, provider, or paid API call was made.
Unit-test and reference-solver results cited below are **instrument**
facts. They are not model performance.

Primary research objective (as given): test whether language-model agents
can discover and use compact compositional representations to solve
local-to-global constraint problems under recursive composition,
hidden/relabelled representations, and global obstructions—not merely
solve small instances by brute force or exploit surface heuristics.

Reviewed:

1. `recursive_gluing_discovery` (primary candidate)
2. `recursive_gluing` (expanded-CSP control)
3. `recursive_holonomy_gluing`
4. `recursive_compiler_bootstrap`
5. `recursive_error_correcting_codes`
6. `recursive_coarse_graining`

Maze / distributed / epistemic families are out of this review’s scoring
scope. They are mentioned only where they affect transfer claims.

## 0. Intended structural solution (algorithmic target)

For each module type \(t\) and remaining depth \(k\), compute the relation
\(S(t,k)\) of realizable boundary states (enter, leave).

- Leaves: \(S(\mathrm{leaf},0)\) is the listed local pair table.
- Recursion: \(S(\mathrm{branch},k)\) is the composition of the children’s
  relations through the wiring/transport tables.
- Root: apply the closing condition to \(S(\mathrm{root},d)\).

A **global obstruction** is: every local relation and every wiring table
may be nonempty, yet no realizable root pair meets closing.

This is a proposed algorithmic target for the *instrument*, not a claim
about model internals. A candidate that emits the unique \(S(t,k)\) tables
has implemented (or simulated) this dynamic program. That is not evidence
that the model possesses a sheaf, a Čech cocycle, or any other named
mathematical object.

## 1. Four claims that must not be collapsed

| Code | Claim | What would support it | What does not |
|---|---|---|---|
| **A** | Implement a known formal algorithm | Agent code (or equivalent) computes \(S(t,k)\) or an isomorphic summary; certificate matches the oracle on the supported class | Prompt restates the recurrence; reference solver passes |
| **B** | Generalize that algorithm to new instances | Held-out seeds, depths, opacities, decoy types, wirings *within the same grammar class*, with A already identified | Accuracy on the training-like easy axis; unit tests of the generator |
| **C** | Transfer the structural principle across task domains | Same agent, no restated DP, succeeds on a *different* native object whose compact solution is the same composition pattern | Four directories that share scaffolding; renamed nouns on tiny state spaces |
| **D** | Discover a sheaf-theoretic interpretation or internal concept | Independent evidence of the concept (open-ended naming, interpretability, transfer to an undescribed sheaf problem) | Success at A–C; stripped vocabulary in the prompt |

Do not imply that success at A–C establishes D.

Do not treat removal of the words sheaf / holonomy / gluing / Čech as
evidence that the underlying structure is hidden. If the input schema and
required certificate *are* \(S(t,k)\), the structure is the task, named or
not.

Do not call `direct` vs `recursive` an isolated structural contrast when
nesting, extra factors, and polarity move together.

Do not call the four-application suite one coherent construct without
evidence. Section 8 argues it is not.

## 2. `recursive_gluing_discovery` — primary candidate

### Exact hypothesis

**H-disc-A.** Given the compact grammar (types, productions, wirings,
closing) the agent can fill `realizable[t][k]` and the SAT bit so that they
match the unique bottom-up summary.

**H-disc-B.** The same procedure remains correct on held-out seeds, per-type
label permutations (`opaque`), decoy leaves, and depths not used in the
visible tests.

**H-disc-compact.** The agent’s method is the compact DP (or something
resource-equivalent), not unfold-then-project.

**H-disc-D.** The agent has discovered a sheaf-theoretic reading of the
grammar. **Not testable with this instrument.**

Observable evidence for A/B: judge `verify_certificate` exact-match on
`realizable` plus SAT iff root summary intersects closing (tree: nonempty).
False SAT / false UNSAT are both failures. Timeout is a runtime error, not
UNSAT (`OracleBudgetExceeded`).

Falsifiers: copy-leaf-upward certificate (starter `solver.py`); SAT on
`cyclic_unsat`; missing depth keys; tables that ignore wiring.

### Competing explanations

| Explanation | Can this design catch it? | Notes |
|---|---|---|
| Brute-force unfolding | **Not at the hard axis** | Expanded CSP at \(d=12\) solves in ~1.0 s and ~4.5 MB JSON (`docs/decisions/2026-10-16-recursive-gluing-scaling.md`). Unfold-then-project still fills `realizable[t][k]`. |
| Generic CSP synthesis | Same | The certificate does not record whether expansion occurred. |
| Memorized translation grammar | Partially | Supported class is leaf \(\delta\)-translations on \(\mathbb Z/q\mathbb Z\), \(q\in\{3,5,7\}\). A model that infers “sum \(2^d\delta\) vs identity” can skip general composition. Decoy `weed` and opaque labels stress this; they do not leave the class. |
| Surface cues | Partially | Starter solver always SAT and copies tip pairs. `cyclic_unsat` plus required exact tables block “always SAT”. Regime name `cyclic_unsat` is **not** in the agent workspace (substituted only in `judge.py`). |
| Genuine compact composition | Not identified | No process measure (allocations, steps as \(O(d q^4)\) vs \(\Theta(2^d)\)). |

### Paired contrasts

| Pair | Intended variable | Isolated? |
|---|---|---|
| `tree` / `cyclic_sat` / `cyclic_unsat` | closing; local tables stay nonempty | **Yes, within the translation class.** SAT polarity of `cyclic_unsat` is the global obstruction. |
| `transparent` / `opaque` | per-type port relabelling | **Presentation only**, answer preserved. Not per-occurrence opacity (documented limitation). |
| `clean` / `decoy` | extra leaf type `weed` | Task change, not presentation. Isolates “treat every leaf as tip”. |
| depth 3 / 6 / 12 | remaining depth; occurrence count \(2^{d+1}-1\) | Input size stays ~1.2 KB. Does **not** isolate compact vs unfold: both run at \(d=12\). |
| vs `recursive_gluing` v0 | compact grammar vs expanded CSP | **Not a matched pair.** v0 hard is \(d=3\) expanded; discovery hard is \(d=12\) compact. Different depths, different certificates (assignment vs `realizable`). |

### Baselines

| Arm | Role | Status |
|---|---|---|
| `arm_compact` / reference certificate | compact compositional reference | Implemented; exact |
| Expanded CSP (`_csp_solution`, AC-3 + backtrack) | exhaustive on the unfolding | Cross-check only at \(d\le 4\) (`MAX_EXPAND_DEPTH = 4`). Measured separately through \(d=15\). |
| `arm_copy_leaf_upward` / starter solver | negative (copy tip upward, always SAT) | Fails assembled_unsat / decoy / twist `[tested]` |
| `arm_given_canonical` | revealed integer coordinates | **Not a distinct solver.** Aliases `arm_compact`. Cannot be scored as a “given latents” arm. |
| Exhaustive over pair-tables | — | Infeasible as a model of the agent; \(q^{q^2}\) etc. The expanded CSP is the feasible exhaustive baseline. |

### Held-out and scaling

Held-out in the grade list: `opaque_twin`, `decoy_heldout`, `heldout_twist`,
plus depths 3/6/12 on the axis. Relabel preserves SAT `[tested]`.

Scaling `[tested, measured]`: compact grammar bytes independent of \(d\)
(~1185 B); certificate \(\Theta(d q)\); compact oracle sub-millisecond
through \(d=96\). Expanded serialization 4.5 MB at \(d=12\), 38 MB at
\(d=15\). **Hard axis \(d=12\) is not a point where expansion is
infeasible.** Materialization becomes expensive around \(d=15\) on the
recorded machine, not at 12. Claiming “the expanded solver cannot run at
hard” is false for this implementation.

### Metrics

Certificate exact match; false SAT; false UNSAT; determinism; timeout ≠
UNSAT. Resource use is measured for the *oracle*, not for a model.
No token, step, or wall-clock model metric exists.

### Threats

- **Construct:** the prompt *states* the inductive certificate. A success
  is A (coding the spec), not D, and only weakly B.
- **Unfolding still cheap at hard.** Compact necessity is not forced.
- **Narrow grammar class.** Translation leaves + bijective wirings;
  AC-3 decides without search. Not a general constraint sheaf.
- **Vocabulary ≠ hidden structure.** Prompt forbids sheaf words and still
  asks for `realizable[t][k]`.
- Ceiling: a competent implementer of the spec scores 1. Floor: copy-leaf
  scores 0 on D-class. The gap is “did you implement the stated DP”.
- Unjustified if a model scores well: discovery of sheaves; that unfolding
  was impossible; transfer to other domains.

### Go / no-go for model calls

**No-go** as a test of D, of compact-vs-brute-force at \(d=12\), or of
cross-domain transfer.

**Conditional go as A (and weak B)** if the operator accepts the construct
“can the agent implement the stated interface DP on this translation
grammar, including opacity and decoy”, and logs tokens/steps vs depth
without interpreting slope as proof of compactness.

## 3. `recursive_gluing` — expanded-CSP control

### Hypothesis

**H-v0.** The agent can return a globally consistent assignment (or UNSAT)
on an *already unfolded* region network with nested ids and pairwise
overlaps.

This is not a compact-representation hypothesis. It is the control in which
the intended DP has been compiled away into a flat CSP.

### Competing explanations

Brute force / AC-3 / backtracking on \(\le 7\) labels and \(\le\) a few
dozen regions at hard (\(d=3\)). Generic CSP. Copy labels across regions
(starter defers cross-depth overlaps). Surface “always SAT”.

Domain sizes 3/5/7; depth 1/2/3. Naive Cartesian is large at \(d=3, q=7\),
but constraint propagation on this bijection-heavy family is cheap. There
is no measured point where exhaustive search is the only remaining method
*and* infeasible.

### Contrasts

`tree` / `cyclic_sat` / `cyclic_unsat`: polarity with nonempty local data
`[tested]`. `transparent` / `opaque`: presentation. Depth adds regions and
skip-level overlaps (structure). **Matched to discovery only as “same
umbrella”, not as the same instance at two encodings.**

### Baselines

Reference assignment / unsat; starter nested-by-slash heuristic fails
cross-level overlaps `[tested]`. Exhaustive: the module’s own CSP solver.

### Threats

Success is A for “solve this CSP”, not B/C/D for compact composition.
Pairing with discovery without matching depth and certificate type
confounds presentation with difficulty.

### Go / no-go

**Go only as a coding control** at \(d\le 3\): does the agent write a
working finite-domain solver. **No-go** as evidence about compact
compositional representations.

## 4. `recursive_holonomy_gluing`

### Hypothesis (charitable)

**H-hol-A.** Compose the listed finite maps (or infer them from calibration)
and decide whether some domain element returns to itself.

That is the intended DP specialized to *functional* relations and diagonal
closing. It is still A. Domain size is 6 (multiplicative \(\mathbb F_7^\times\)),
7 (affine), or 4 (permutation). Exhaustive search of the domain is cheaper
than talking about composition.

### Competing explanations

Enumerate the domain and apply maps (brute force — **not distinguishable**
from composition at this size). Infer maps from calibration (inferred
mode; maps are uniquely determined). Always SAT (starter). Directory name
`recursive_holonomy_gluing` leaks the word holonomy on the host; it does
not appear in the agent workspace `[tested]`. Prompt still specifies
family, cycle order, and returning state — structure is not hidden.

### Contrasts (runner-selectable only)

Config levels: `direct` / `recursive` / `recursive_composition`.
Generator `flat` **cannot** be selected (`docs/audits/2026-10-17-four-apps-evaluation-readiness.md`).

| Pair | What moves | Isolated? |
|---|---|---|
| `recursive` vs `recursive_composition` | extra factor SAT vs no returning state; same cycle shape | Polarity on matched shape. Yes for polarity. Not “more nesting”. |
| `direct` vs `recursive` | extra factor **and** `root=node` at \(d\ge 2\); both SAT | **Confounded.** Do not call this an isolated structural contrast. |
| revealed vs inferred | maps listed vs calibration | Inferred maps are reconstructible. Weak hide. |
| family mul/aff/perm | algebraic presentation | Transfer *within* maps, not across domains. |

### Baselines

Reference compose+enumerate, accuracy 1; local-only / nonempty-domain ⇒ SAT
accuracy 0 on held-out REC_COMP (\(n=12\)) `[tested]`. Exhaustive baseline
**is** the reference (domain enumeration). Compact compositional reference
**is the same function** — there is no size gap.

### Scaling

Public payload ~300 B; cycle length \(= d\) or \(d+1\). No exponential
unfolding.

### Threats

Ceiling: both brute force and composition succeed. Floor: local-only fails
D-class. Gap tests shortcut heuristics, not compact vs brute. Construct C
(transfer of discovery’s \(S(t,k)\)) fails: the certificate is
`{status, state, maps}`, not interface summaries. D unjustified.

### Go / no-go

**No-go** for the primary objective (compact vs brute force under
recursion). **No-go** as a transfer target for C until the certificate and
size regime match discovery. Optional later coding toy only.

## 5. `recursive_compiler_bootstrap`

### Hypothesis (actual)

**H-cmp.** For a finite listed program set, source evaluation equals
bytecode obtained by compile → last-stage encoding → `claimed_decoder`.
Local stages may all be correct under their own encodings while the path
claim is false.

This is observational equivalence of interpreters, not boundary-relation
composition. Treating it as the same construct as discovery is a category
error.

### Competing explanations

Execute the six sampled programs (grammar height \(\le 2\), constants
\(\{0,1,2\}\)). Trust the claimed decoder (starter). Recover encodings from
calibration. Memorize opcode permutation \(\{0,1,2\}\).

### Contrasts

`recursive` vs `recursive_composition`: **same two stages**, wrong vs right
claimed decoder — polarity on matched structure. `direct` vs `recursive`:
one stage vs two, both True — confounded. `flat` not selectable. Depth axis
is grammar height capped at 2; requested 3 records 2. Not AST-depth
generalization.

### Baselines

Reference interpreters; local-only `equivalent=True` accuracy 0 on REC_COMP
(\(n=8\)) `[tested]`. Exhaustive: evaluate every listed program (at most 6).

### Threats

Wrong native object for the primary objective. Tiny finite set. Prompt
describes the claim. Success at “path decoder ≠ local stages” is a
different hypothesis, not C from discovery, not D.

### Go / no-go

**No-go** for the sheaf/compositional-representation objective.
Do not fold into a four-app transfer battery.

## 6. `recursive_error_correcting_codes`

### Hypothesis (charitable)

**H-cod.** Local kernels of \(H=[1\,1]\) over \(\mathbb F_5\) may be
nonempty while the stacked glue + parent system is empty.

A compact analogue of \(S(t,k)\) would be “symbols realizable at each
block after overlaps”. The instrument does not ask for that table. It asks
for a SAT assignment or UNSAT. The oracle enumerates \(5^{2d}\) (25 / 625 /
15625 at depths 1/2/3). Exhaustive search is the reference.

### Contrasts

`recursive` vs `recursive_composition`: same cycle overlaps, parent rhs
0 vs 1 — polarity on matched structure. `direct` vs `recursive`: overlaps
added, both SAT — confounded. `flat` not selectable. Inferred perms: \(H\)
is symmetric, calibration does not uniquely determine a length-2 perm —
weak, partly unspecified hide. Field name `glues` is a schema identifier.

### Baselines

Reference enumerator accuracy 1; local-only SAT accuracy 0 on REC_COMP
(\(n=6\)) `[tested]`. Exhaustive = reference. No compact certificate.

### Threats

Cannot separate brute force from “compositional” linear algebra at
\(5^6\). Not the discovery DP. Not one construct with compiler or coarse.

### Go / no-go

**No-go** for the primary objective.

## 7. `recursive_coarse_graining`

### Hypothesis (actual)

**H-crs.** Exact 2-spin integer tables: leaf \(T[L,R]=\sum_s W[L,s,R]\);
series \(T_{12}[L,R]=\sum_m T_1[L,m]T_2[m,R]\); `fixed` iff \(T\circ T=T\).

Series composition is algebraically similar to relation composition on a
2-point boundary. The *question* is “effective table and doubling
stability”, not “global section vs obstruction of a constraint sheaf”.
It is a 2-spin nonnegative integer toy, not a lattice RG model.

### Contrasts

`recursive` vs `recursive_composition`: same series tree, projector vs
all-ones weights — polarity on matched geometry. `direct` vs `recursive`:
one region vs series, both fixed — confounded. `flat` (one all-ones
region, not fixed) is generator-only. Inferred `label_perm` is a 1-bit
swap. Depth on `direct` records 1 even if the axis says 3.

### Baselines

Reference exact tables; first-region `fixed=True` accuracy 0 on REC_COMP
(\(n=6\)) `[tested]`. Exhaustive: 2×2 integer arithmetic.

### Threats

Ceiling at 2×2. Wrong question for local-to-global SAT. Prompt already
gives the sum-product rule (A, not D). Vocabulary strip (“stable under
doubling”) does not hide the algebra.

### Go / no-go

**No-go** for the primary objective and for physics claims.

## 8. The four-application suite is not one construct

Shared scaffolding (layout, `public_instance`, grade names, regime
*strings*) is not a shared scientific construct.

| Env | Native object | Oracle | Compact DP of §0? | Exhaustive cheap? |
|---|---|---|---|---|
| discovery | grammar + wirings | \(S(t,k)\) | **Yes (the definition)** | No at \(d=15+\); **yes at hard \(d=12\)** |
| v0 | unfolded CSP | assignment | Compiled away | Yes at \(d=3\) |
| holonomy | finite maps | compose + enumerate domain | Functional special case | Yes (\(\lvert\mathrm{dom}\rvert\le 7\)) |
| compiler | interpreters | run programs | No | Yes (6 programs) |
| codes | \(\mathbb F_5\) blocks | enumerate \(5^{2d}\) | Not requested | Yes (\(\le 15625\)) |
| coarse | 2-spin tables | sum-product | Similar algebra, different question | Yes (2×2) |

A model that scores on all four applications has not been shown to
transfer a structural principle (C). It may have implemented four small
specs (four times A). Cross-domain transfer would require, at minimum: the
same compact certificate schema or a documented isomorphism; size regimes
where brute force is dominated; unconfounded polarity and presentation
contrasts; and a pre-registered analysis that does not drop failed domains.

`flat` as A/B/C/D in older notes is a generator constant, not a runner
level. Do not design a matrix that assumes four selectable regimes.

## 9. Recommended experiment matrix

Pre-register the claim as **A, optionally weak B**, on discovery only.
Do not pre-register C or D.

| Slot | Env | Depth | Regime | Opacity | Ambiguity | Role |
|---|---|---|---|---|---|---|
| 1 | discovery | 6 | `cyclic_sat` | transparent | clean | Positive polarity |
| 2 | discovery | 6 | `cyclic_unsat` | transparent | clean | Global obstruction; matched shape |
| 3 | discovery | 6 | `cyclic_unsat` | opaque | clean | Presentation twin of 2 |
| 4 | discovery | 6 | `tree` | transparent | clean | Closing absent |
| 5–8 | discovery | 12 | same four | same | clean | Depth scaling of *tokens/steps*, not a compactness proof |
| Optional | discovery | 6 | `cyclic_unsat` | transparent | decoy | Only if 1–4 already show A |
| Optional control | v0 | 3 | `cyclic_unsat` | transparent | — | Expanded-CSP coding control; **not** matched difficulty |

Do not include holonomy / compiler / codes / coarse in the first matrix.
If C is ever attempted, it needs a new instrument (shared compact
certificate, larger state spaces), not a joint score over the current four.

Analysis: per-cell SAT accuracy, false SAT vs false UNSAT, exact
`realizable` match rate, tokens and solver runtime vs \(d\). Treat a flat
runtime vs \(d\) as *consistent with* compact DP, not as proof (unfolding
at \(d=12\) is also fast). Copy-leaf and always-SAT are the negative
baselines; compact reference is not a model.

## 10. Remaining blockers that affect validity

Logistics (no API keys, no model run) are real and already recorded. They
are not the validity blockers.

1. **The discovery prompt is the algorithm.** A cannot be separated from
   “follow the spec” without a prompt that does *not* demand \(S(t,k)\).
2. **Hard depth does not forbid unfolding.** \(d=12\) expanded solves in
   ~1 s. Compact necessity is unforced.
3. **Certificate is compatible with unfold-then-project.** No process
   observable distinguishes that from the compact DP.
4. **`arm_given_canonical` is not an arm.** Revealed-coordinates contrast
   does not exist.
5. **Opacity is per type, not per occurrence.**
6. **Grammar class is translations on \(\mathbb Z/q\mathbb Z\).** A closed
   form can replace composition.
7. **v0 and discovery are unmatched** in depth and certificate.
8. **Four apps are four constructs**; brute force is cheap on all four;
   `direct` vs `recursive` is confounded; `flat` is not selectable.
9. **Vocabulary removal does not hide structure.**
10. **No model metric for resource use** is wired through the judge, so
    even a pilot cannot currently *test* H-disc-compact—only describe
    coarse runtime.

Blockers 1–3, 8, 9 remain even if keys appear tomorrow.

## 11. Smallest defensible pilot

Four discovery episodes, one model, one seed pair:

- depth 6, `cyclic_sat`, transparent, clean, seeds \(\{0,1\}\)
- depth 6, `cyclic_unsat`, transparent, clean, seeds \(\{0,1\}\)

That is the polarity contrast on matched grammar shape (the one unconfounded
SAT contrast discovery actually has). Budget: those four cases, no paid
fallback, stop on provider error.

**What a high score would justify:** the agent implemented something that
agrees with the stated DP on this polarity pair at \(d=6\) (claim A, this
slice).

**What it would not justify:** B beyond these seeds; compact vs unfold;
C across domains; D sheaf concepts; that the four-app suite measures one
ability.

**Go criterion to spend those four calls:** operator accepts A-only;
credentials verified no-cost; `tools/provider_preflight.py` reachable;
suite manifest filtered to discovery; `--max-cases 4`; no four-app
episodes in the same run.

**No-go otherwise.** The instrument is not yet a test of the primary
research objective as written.

## 12. Claims this review does not make

- Any model recovered \(S(t,k)\), maps, encodings, codewords, or tables.
- Reference-solver or unit-test pass is structural reasoning.
- These tests are a validated benchmark.
- The four applications are one construct.
- `direct` vs `recursive` isolates nesting.
- `flat` is an experimental arm.
- Stripped theory words hide the task structure.
- Success at A–C would be success at D.
