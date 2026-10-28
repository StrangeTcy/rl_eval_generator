# Recursive program discovery

This is an implemented, unexecuted environment for learning hidden local interpreter rules from shallow observations and predicting nested compositions. It is separate from recursive-gluing and from recursive opponent modelling.

The complete contract, difficulty axes, hand-derived controls, and readiness obligations are in [RECURSIVE_PROGRAMS.md](../../research_program/dialogue_2026_10_28/RECURSIVE_PROGRAMS.md).

The controller owns initialization and private rule seeds. The future isolated entry point is `python -m arena.recursive_programs`; this command has not been run.

```text
recursive 13 29 3 2 2 6 balanced distinct 0 7
```

The fields are semantic seed, private rule seed, public target depth, active operator count, coefficient width, query budget, tree shape, subtree condition, free demonstrations per operator, and modulus. The agent receives only public observations after initialization.

```text
probe A 0 0
probe A 1 0
probe A 0 1
```

A terminal action gives three predicted residues and one coefficient triple per active operator:

```text
answer 1 0 6 model 2 1 1 1 2 0
```

The terminal line is a hand-worked illustration, not the answer to the example controller configuration.

`PublicSolver` reads public text, gathers an identifying basis, and predicts by expanding path-weighted contributions. It does not import the engine. `ShallowSolver` learns the same local rules but collapses internal children to their first leaves; `ZeroSolver` supplies a constant-output rival. `Trial` is for trusted scripted policies; `Replay` reconstructs from controller configuration and valid actions. Untrusted evaluated code requires a separate authorized process or container and must not share the engine's address space.

The new regression module is `tests/test_recursive_programs.py`. No tests, episodes, provider calls, or local commands were run for this implementation. Future validation should use focused `unittest` discovery in an authorized isolated checkout. The parent Arena import requires Python 3.11 or newer; the repository's pytest completion hook has campaign side effects in eligible CI contexts, so ordinary pytest is not the proposed readiness route.
