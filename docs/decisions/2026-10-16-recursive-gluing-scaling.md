# Recursive gluing discovery: measured scaling

Date: 2026-10-16. Companion to `2026-10-16-recursive-gluing-discovery.md`.
Machine-readable copy: `2026-10-16-recursive-gluing-scaling.json`.

This report records a compact-vs-expanded measurement on the production
generator, compact oracle, `expand_grammar`, and expanded CSP (`_csp_solution`).
It does not evaluate a model.

## How to reproduce

```bash
python tools/recursive_gluing_scaling.py \
  --json docs/decisions/2026-10-16-recursive-gluing-scaling.json
```

Defaults used here: `--seed 0 --interface-size 5 --regime cyclic_unsat --opacity opaque --ambiguity clean --repeats 3`, compact depths 3,6,12,24,48,96, expand depths 3,6,9,12, attempt depth 15 in an isolated subprocess (1536 MB address-space cap, 90 s timeout).

Recorded environment: CPython 3.11.2, Linux 6.1.158+ x86_64 glibc 2.36. Wall times are `time.perf_counter` medians over three repeats. Peak memory is `resource.ru_maxrss` of the worker process (Linux KB). Grammar generation, expansion, serialization, compact oracle, certificate verification, and CSP solving are timed separately. The expanded worker does not call `compact_summaries`.

Cells below are **measured** unless marked **analytic** (exact combinatorial counts, no process ran) or **estimate** (linear extrapolation from measured RSS, stated as such).

## Formulas (exact)

For remaining depth \(d\) with optional root closing:

| quantity | formula | d=3 | d=12 | d=15 | d=24 |
|---|---|---:|---:|---:|---:|
| occurrences | \(2^{d+1}-1\) | 15 | 8191 | 65535 | 33554431 |
| leaves | \(2^d\) | 8 | 4096 | 32768 | 16777216 |
| port variables | \(2\times\) occurrences | 30 | 16382 | 131070 | 67108862 |
| overlaps (with closing) | \(2^{d+2}-3+1\) | 30 | 16382 | 131070 | 67108862 |

Validated against `expand_grammar` on d=1..4 and on every successfully materialized row below.

For this translation grammar the compact certificate has `interface_size * (depth + 1)` pair-cells (tip at 0, stem at 1..d): 20, 35, 65, 125, 245, 485 at the compact depths.

## Compact (measured)

| d | occurrences (exact) | grammar bytes | cert bytes | summary cells | depth keys | gen ms | oracle ms | verify ms | RSS KB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 15 | 1184 | 434 | 20 | 4 | 0.075 | 0.077 | 0.060 | 15024 |
| 6 | 127 | 1184 | 722 | 35 | 7 | 0.103 | 0.109 | 0.080 | 14992 |
| 12 | 8191 | 1185 | 1301 | 65 | 13 | 0.075 | 0.149 | 0.158 | 15036 |
| 24 | 33554431 | 1185 | 2465 | 125 | 25 | 0.073 | 0.264 | 0.256 | 15068 |
| 48 | \(2^{49}-1\) | 1185 | 4793 | 245 | 49 | 0.075 | 0.443 | 0.416 | 15156 |
| 96 | \(2^{97}-1\) | 1185 | 9449 | 485 | 97 | 0.075 | 0.770 | 0.789 | 15204 |

Status was `unsat` at every depth (cyclic_unsat, q=5 odd, \(2^d \not\equiv 0 \pmod 5\)).

The agent-visible grammar size is independent of depth up to the decimal encoding of `depth` itself. Certificate size and summary cells grow linearly with d. Worker RSS is ~15 MB at every compact depth: that is process baseline, not a depth-dependent heap. The oracle does not allocate the unfolding.

## Expanded (measured, then analytic)

| d | kind | occ | vars | overlaps | serialized bytes | expand ms | serialize ms | solve ms | sat | RSS KB |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 3 | measured | 15 | 30 | 30 | 6704 | 0.060 | 0.145 | 0.961 | false | 15100 |
| 6 | measured | 127 | 254 | 254 | 60816 | 0.503 | 0.940 | 8.010 | false | 16556 |
| 9 | measured | 1023 | 2046 | 2046 | 525968 | 4.137 | 7.923 | 69.637 | false | 28268 |
| 12 | measured | 8191 | 16382 | 16382 | 4505232 | 42.015 | 51.983 | 1040.792 | false | 120312 |
| 15 | measured | 65535 | 131070 | 131070 | 38403728 | 764.460 | 801.622 | 12554.496 | false | 858212 |
| 24 | analytic | 33554431 | 67108862 | 67108862 | — | — | — | — | — | — |
| 48 | analytic | \(2^{49}-1\) | \(2^{50}-2\) | \(2^{50}-2\) | — | — | — | — | — | — |
| 96 | analytic | \(2^{97}-1\) | \(2^{98}-2\) | \(2^{98}-2\) | — | — | — | — | — | — |

Depth 15 succeeded under the declared 1536 MB / 90 s attempt budget. Depths ≥ 24 were not materialized.

**Estimate (not measured):** subtracting the ~15 MB process baseline from d=12 and d=15 RSS gives ~12.8 KB of worker RSS per occurrence. Linear in occurrences, d=24 would be on the order of 400 GB RSS. That is an extrapolation from two points on this implementation and machine; it is not a measurement.

## What the numbers support

**Representation advantage (mathematical, confirmed).** The compact grammar stays ~1.2 KB while unfolded occurrence count is \(2^{d+1}-1\). At d=12 the expanded serialization is 4.5 MB (about 3800× the grammar); at d=15 it is 38 MB. The certificate grows as Θ(d q), never one record per occurrence.

**Runtime advantage (measured on this solver, this machine).** Compact oracle time stays sub-millisecond through d=96. Expanded CSP time is 1.0 s at d=12 and 12.6 s at d=15. Expansion cost and solve cost are both visible; solve dominates. Compact is faster on every measured depth. The gap grows with d because the compact step is O(d q⁴) while AC-3 runs over Θ(2^d) variables.

**What this is not.** Occurrence count is exponential in d; expanded *runtime* on this grammar is not an exponential search. The wirings are bijections, so propagation decides SAT without exploring 5^{16382} assignments. From d=6 to d=15, solve time scales roughly with occurrence count (8 ms → 12.6 s, about 1600× for 516× more occurrences), not with a combinatorial explosion of the search tree. Depth 12 is still cheap enough to materialize on a laptop-class process. Claiming “the expanded solver cannot run at the hard axis” is false for this implementation: the hard axis is d=12, which expanded in 42 ms and solved in 1.0 s.

Materialization becomes *meaningfully expensive* on this machine at d=15 (~838 MB above baseline, 12.6 s solve, 38 MB JSON), not at d=12. d=24 was not attempted.

## Claims that remain unproven

- No model was run. Compact-oracle success is not evidence of latent-structure discovery.
- `arm_given_canonical` is the compact oracle under another name. A revealed-coordinates experimental condition has not been implemented as a distinct solver and has not been run.
- Per-occurrence label opacity is not implemented. `label_opacity` / `relabel_grammar` permute labels **per module type**. Expanded stem occurrences share one domain.
- RSS of the compact worker does not resolve oracle allocations below process baseline.
- Results depend on CPython, this AC-3 solver, bijection-heavy instances, and this machine.

Command exit code was 0. Campaign state was not read or written.
