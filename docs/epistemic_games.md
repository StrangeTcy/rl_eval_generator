# Epistemic-games family

> **Metis move tested:** frame resistance and proof/provenance discipline.

The epistemic-games family tests whether an agent follows public evidence rather
than allowing a narrative frame to become an unstated premise. Narrative and
bare-table presentations, balanced and skewed priors, evidence-strength bands,
and paired-world observational-equivalence cases separate arithmetic from
framing and provenance errors.

The family has a public-only deterministic oracle. It is a reference-consistency
check that makes zero provider calls; it is not evidence about a model's private
reasoning process or hidden architecture. Run it before a model sweep through
the suite's oracle preflight rather than treating provider access as a substitute
for reference validation.

The generated environment is configured at
`envs/epistemic_games/config.yaml`. The conceptual taxonomy is in
[`metis.md`](metis.md), and the public oracle is implemented in
`tools/public_bayes_oracle.py`.

Report narrative-versus-bare results with the evidence band, prior, seed, and
failure mode. A narrative failure may indicate framing capture, but it may also
reflect parsing, underspecification, or a different valid interpretation; use
the paired controls and provenance fields before making a stronger claim.
