"""The typed interface between a research question and a generated family.

A spec says what an experiment claims, not what an environment contains.  This is
the seam the epistemic compiler aims at: hypotheses, the measurements that
distinguish them, the controls that would falsify them, and the environment members
that produce those measurements.  Nothing here executes a model, imports the
compiler, or runs a container - it validates and compiles, so an incoherent
experiment fails before a single environment is generated.

The blocking rules are the point (``--allow-advisory`` exists for drafts).  A spec
whose primary hypothesis has no control, or whose "competing explanation" is
missing, is not a weaker experiment; it is an unexecuted one, because whatever the
members measure, nothing in the family distinguishes the two claims.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

SPEC_VERSION = 1
REQUIRED_TOP_LEVEL = ("spec_version", "id", "hypotheses", "measurements", "members")
HYPOTHESIS_KINDS = ("primary", "competing", "null")
CONTROL_KINDS = (
    "evaluator_preserving_twin",
    "presentation_preserving_twin",
    "task_changing_twin",
    "baseline",
    "held_out_seed",
    "oracle_validity",
)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _names(entries: Sequence[Any], where: str, errors: list[str]) -> list[str]:
    names: list[str] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, Mapping):
            name = str(entry.get("id") or "").strip()
        else:
            errors.append(f"{where}[{index}]: must be a string or a mapping with an 'id'")
            continue
        if not name:
            errors.append(f"{where}[{index}]: missing 'id'")
            continue
        if name in names:
            errors.append(f"{where}: duplicate id {name!r}")
        names.append(name)
    return names


def validate_spec(
    spec: Mapping[str, Any],
    *,
    taxonomy: Mapping[str, Mapping[str, Any]] | None = None,
    implemented: Mapping[str, Sequence[str]] | None = None,
    known_environments: Sequence[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for one environment-experiment specification.

    ``implemented`` maps environment name -> intervention ids it actually realizes.
    Without it, an unknown id is only checked against the taxonomy, which catches
    typos but not an intervention the target environment cannot perform; the family
    expander passes it and turns the second class into an error too.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(spec, Mapping):
        return (["spec must be a mapping"], warnings)

    for key in REQUIRED_TOP_LEVEL:
        if key not in spec:
            errors.append(f"missing required key: '{key}'")
    if errors:
        return (errors, warnings)

    if int(spec["spec_version"] or 0) != SPEC_VERSION:
        errors.append(
            f"spec_version {spec['spec_version']!r} is not supported (this generator emits {SPEC_VERSION})"
        )
    if not _is_nonempty_str(spec["id"]):
        errors.append("'id' must be a non-empty string")

    hypotheses = spec["hypotheses"]
    if not isinstance(hypotheses, Sequence) or isinstance(hypotheses, (str, bytes)):
        errors.append("'hypotheses' must be a list")
        hypotheses = []
    hypothesis_ids: list[str] = []
    for index, hypothesis in enumerate(hypotheses):
        where = f"hypotheses[{index}]"
        if not isinstance(hypothesis, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        if not _is_nonempty_str(hypothesis.get("id")):
            errors.append(f"{where}: missing 'id'")
            continue
        if not _is_nonempty_str(hypothesis.get("statement")):
            errors.append(f"{where}: missing 'statement'")
        kind = str(hypothesis.get("kind") or "primary")
        if kind not in HYPOTHESIS_KINDS:
            errors.append(f"{where}: kind {kind!r} must be one of {', '.join(HYPOTHESIS_KINDS)}")
        hypothesis_ids.append(str(hypothesis["id"]))
    # The anti-"idea soup" rule: one claim with no rival is a description, not a
    # hypothesis, because nothing in the family could have refuted it.
    if len(hypothesis_ids) < 2:
        errors.append(
            "a spec needs at least two hypotheses: the claim and a competing "
            "explanation. Members can then be scored for which of the two they "
            "support, which is the only thing a generated family can establish"
        )

    measurements = spec["measurements"]
    if not isinstance(measurements, Sequence) or isinstance(measurements, (str, bytes)):
        errors.append("'measurements' must be a list")
        measurements = []
    measurement_ids = _names(list(measurements), "measurements", errors)

    members = spec["members"]
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes)) or not members:
        errors.append("'members' must be a non-empty list")
        members = []

    declared_member_ids = {
        str(member.get("id") or f"member-{index}")
        for index, member in enumerate(members)
        if isinstance(member, Mapping)
    }

    controls = spec.get("controls") or []
    if not isinstance(controls, Sequence) or isinstance(controls, (str, bytes)):
        errors.append("'controls' must be a list")
        controls = []
    controlled_for: set[str] = set()
    for index, control in enumerate(controls):
        where = f"controls[{index}]"
        if not isinstance(control, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        kind = str(control.get("kind") or "")
        if kind and kind not in CONTROL_KINDS:
            errors.append(f"{where}: kind {kind!r} must be one of {', '.join(CONTROL_KINDS)}")
        named_member = control.get("member")
        if named_member is not None and str(named_member) not in declared_member_ids:
            errors.append(f"{where}: controls unknown member {named_member!r}")
        target = control.get("hypothesis")
        if target is None:
            errors.append(f"{where}: controls must name the hypothesis they control for")
            continue
        if str(target) not in hypothesis_ids:
            errors.append(f"{where}: controls unknown hypothesis {target!r}")
        else:
            controlled_for.add(str(target))

    taxonomy = taxonomy or {}
    produced: set[str] = set()
    addressed: set[str] = set()
    baseline_seen = False

    for index, member in enumerate(members):
        where = f"members[{index}]"
        if not isinstance(member, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        member_id = member.get("id") or f"member-{index}"
        where = f"members[{member_id}]"
        if not _is_nonempty_str(member.get("environment")):
            errors.append(f"{where}: missing 'environment'")
            continue
        environment = str(member["environment"])
        if known_environments is not None and environment not in known_environments:
            errors.append(f"{where}: environment {environment!r} is not in envs/registry.yaml")
        if not _is_nonempty_str(member.get("difficulty")):
            errors.append(
                f"{where}: missing 'difficulty' (one level per axis, comma-separated, "
                "exactly as generate_env.py takes it)"
            )

        interventions = [str(item) for item in (member.get("interventions") or [])]
        if not interventions:
            baseline_seen = True
        supported_here = None
        if implemented is not None:
            supported_here = set(implemented.get(environment, ()))
            if not supported_here:
                errors.append(
                    f"{where}: environment {environment!r} implements no interventions, so "
                    "it can only be a baseline member"
                )
        for iid in interventions:
            entry = taxonomy.get(iid)
            if entry is None:
                errors.append(f"{where}: intervention {iid!r} is not in the taxonomy")
                continue
            if supported_here is not None and iid not in supported_here:
                errors.append(
                    f"{where}: environment {environment!r} does not implement {iid!r}"
                )
                continue
            expect = member.get("expect")
            equivalence = str(entry.get("equivalence") or "")
            if expect == "invariant" and equivalence in ("observation_changing", "task_changing"):
                errors.append(
                    f"{where}: expects invariance under {iid!r}, which the taxonomy "
                    "declares observation- or task-changing; either the member's "
                    "expectation or the intervention is mislabeled"
                )
            elif expect == "invariant" and equivalence == "evaluator_changing":
                warnings.append(
                    f"{where}: invariance under an evaluator substitution holds for "
                    "task-optimal behavior only - a score change here is a result, not "
                    "a failure of the environment"
                )
            elif expect == "sensitive" and equivalence == "semantically_equivalent":
                errors.append(
                    f"{where}: expects a behavior change from {iid!r}, which is declared "
                    "semantically equivalent; if it does move the answer, the environment "
                    "is mislabelled"
                )

        for measurement in member.get("measurements") or []:
            name = str(measurement)
            if name not in measurement_ids:
                errors.append(f"{where}: produces unknown measurement {name!r}")
            else:
                produced.add(name)
        for hypothesis in member.get("hypotheses") or []:
            if str(hypothesis) not in hypothesis_ids:
                errors.append(f"{where}: bears on unknown hypothesis {hypothesis!r}")
            else:
                addressed.add(str(hypothesis))

    unproduced = [name for name in measurement_ids if name not in produced]
    if unproduced:
        errors.append(
            "no member produces: " + ", ".join(unproduced)
            + " - a measurement with no member is a wish, not an experiment"
        )
    for hypothesis in hypothesis_ids:
        if hypothesis not in controlled_for:
            errors.append(
                f"hypothesis {hypothesis!r} has no control - without one, every member "
                "is equally consistent with it"
            )
        if hypothesis not in addressed:
            errors.append(f"hypothesis {hypothesis!r} is not borne on by any member")
    if members and not baseline_seen:
        errors.append(
            "every member carries an intervention: with no untouched baseline there is "
            "nothing to compare sensitivity against, and the family cannot report an "
            "invariance at all"
        )

    if not _is_nonempty_str(spec.get("claim_ceiling")):
        warnings.append(
            "no claim_ceiling: results from this family will be read as stronger than "
            "they are"
        )
    confounds = spec.get("confounds") or []
    if isinstance(confounds, Sequence) and not isinstance(confounds, (str, bytes)):
        for index, confound in enumerate(confounds):
            if not _is_nonempty_str(confound):
                errors.append(f"confounds[{index}]: must be a non-empty string")
    else:
        errors.append("'confounds' must be a list of named confounds")

    return (errors, warnings)


def compile_members(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract the member list the family expander generates, in declaration order."""
    compiled: list[dict[str, Any]] = []
    for index, member in enumerate(spec.get("members") or []):
        if not isinstance(member, Mapping):
            continue
        compiled.append(
            {
                "id": str(member.get("id") or f"member-{index}"),
                "environment": str(member.get("environment")),
                "difficulty": str(member.get("difficulty")),
                "interventions": [str(item) for item in (member.get("interventions") or [])],
                "expect": str(member.get("expect") or "unspecified"),
                "measurements": [str(item) for item in (member.get("measurements") or [])],
                "hypotheses": [str(item) for item in (member.get("hypotheses") or [])],
                "seeds": [int(seed) for seed in (member.get("seeds") or [0])],
            }
        )
    return compiled


def summarize(spec: Mapping[str, Any]) -> str:
    """One-line human description used in family manifests and CI logs."""
    return (
        f"{spec.get('id')}: {len(spec.get('hypotheses') or [])} hypotheses, "
        f"{len(spec.get('measurements') or [])} measurements, "
        f"{len(spec.get('members') or [])} members"
    )
