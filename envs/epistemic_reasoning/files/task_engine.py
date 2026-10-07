"""Seeded finite tasks built from the accepted epistemic components.

The source APIs remain the semantic core. This module adds only explicit JSON
adapters, finite-instance generation, and task-specific answer serialization.
No floating-point probability arithmetic is used.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from common_knowledge import common_knowledge
from epistemic_relations import (
    EpistemicModel as RelationalModel,
)
from epistemic_relations import (
    ModelError,
    S5EpistemicModel,
)
from epistemic_relations import (
    World as WorldRecord,
)
from event_bayes import (
    EpistemicEvent,
    SpecError,
    calculate_posterior_sparse,
    calculate_posterior_strict,
)
from fragmented_observation import information_set, joint_information
from public_announcements import (
    EpistemicModel as PropositionalModel,
)
from public_announcements import (
    Formula,
    announce_sequence,
    announce_sequence_checked,
    atom,
    knows,
    neg,
)
from silence import update_on_silence
from supplied_policy import StrictSuppliedPolicyInstance, SuppliedPolicyInstance, bayes_update


class TaskSpecError(ValueError):
    """Invalid serialized task input or unsupported task configuration."""


VARIANT_TITLES = {
    "event_sparse": "named-event Bayesian update (sparse contract)",
    "event_strict": "named-event Bayesian update (strict contract)",
    "policy_sparse": "full supplied-policy update (sparse contract)",
    "policy_strict": "full supplied-policy update (strict contract)",
    "relational_modal": "general relational knowledge",
    "s5_knowledge": "partition-based S5 knowledge",
    "announcement_unpointed": "unpointed sequential public announcements",
    "announcement_checked": "actual-world-checked sequential announcements",
    "deterministic_silence": "deterministic information from silence",
    "silence_empty_protocol": "silence with an empty deterministic protocol",
    "common_knowledge": "common knowledge by full reachability closure",
    "common_knowledge_empty_group": "common knowledge for an empty agent group",
    "information_pool": "individual and pooled information",
    "information_empty_group": "pooled information for an empty group",
}

SIZE_LEVELS = ("compact", "expanded")
_WORLD_LABELS = (
    "amber",
    "birch",
    "cobalt",
    "dune",
    "ember",
    "fjord",
    "garnet",
    "hazel",
    "indigo",
    "juniper",
    "kelp",
    "linen",
    "mosaic",
    "ochre",
    "plume",
    "quartz",
)
_FRACTION_RE = re.compile(r"-?(?:0|[1-9][0-9]*)/[1-9][0-9]*\Z")


def encode_fraction(value: Fraction) -> str:
    """Serialize an exact Fraction as a reduced ``numerator/denominator`` string."""
    if type(value) is not Fraction:
        raise TypeError("only Fraction values may be serialized as probabilities")
    return f"{value.numerator}/{value.denominator}"


def decode_fraction(value: object, *, label: str = "rational") -> Fraction:
    """Decode the adapter's canonical rational string; floats and decimals fail."""
    if type(value) is not str or not _FRACTION_RE.fullmatch(value):
        raise TaskSpecError(f"{label} must be a canonical exact fraction string")
    numerator, denominator = value.split("/", 1)
    try:
        exact = Fraction(int(numerator), int(denominator))
    except (ValueError, ZeroDivisionError) as exc:
        raise TaskSpecError(f"invalid {label}") from exc
    if encode_fraction(exact) != value:
        raise TaskSpecError(f"{label} must be reduced with a positive denominator")
    return exact


def serialize_formula(spec: object) -> dict[str, Any]:
    """Validate/copy the JSON formula grammar used to construct accepted callables.

    The adapter is deliberately explicit rather than attempting to serialize
    arbitrary Python callables. Supported nodes are ``atom``, ``neg``, and
    ``knows``; the latter stores an agent and a nested formula.
    """
    if type(spec) is not dict or len(spec) != 1:
        raise TaskSpecError("formula must be a one-key object")
    key, value = next(iter(spec.items()))
    if key == "atom":
        if type(value) is not str or not value:
            raise TaskSpecError("atom name must be a nonempty string")
        return {"atom": value}
    if key == "neg":
        return {"neg": serialize_formula(value)}
    if key == "knows":
        if type(value) is not dict or set(value) != {"agent", "formula"}:
            raise TaskSpecError("knows node requires exactly 'agent' and 'formula'")
        agent = value["agent"]
        if type(agent) is not str or not agent:
            raise TaskSpecError("knowledge agent must be a nonempty string")
        return {"knows": {"agent": agent, "formula": serialize_formula(value["formula"])}}
    raise TaskSpecError(f"unsupported formula node: {key!r}")


def formula_from_json(spec: object) -> Formula:
    """Deserialize the documented JSON AST into accepted callable formulas."""
    copied = serialize_formula(spec)
    if "atom" in copied:
        return atom(copied["atom"])
    if "neg" in copied:
        return neg(formula_from_json(copied["neg"]))
    knows_node = copied["knows"]
    return knows(knows_node["agent"], formula_from_json(knows_node["formula"]))


def _general_formula_from_json(
    spec: object, model: RelationalModel
) -> Callable[[WorldRecord], bool]:
    copied = serialize_formula(spec)
    if "atom" in copied:
        proposition = copied["atom"]

        def evaluate_atom(world: WorldRecord) -> bool:
            if proposition not in world.properties:
                raise ModelError(f"unknown proposition: {proposition}")
            result = world.properties[proposition]
            if type(result) is not bool:
                raise ModelError(f"proposition {proposition!r} is not Boolean")
            return result

        return evaluate_atom
    if "neg" in copied:
        inner = _general_formula_from_json(copied["neg"], model)
        return lambda world: not inner(world)
    node = copied["knows"]
    inner = _general_formula_from_json(node["formula"], model)
    return lambda world: model.knows(node["agent"], world.id, inner)


def _world_ids(rng: random.Random, count: int) -> list[str]:
    if not 1 <= count <= len(_WORLD_LABELS):
        raise TaskSpecError("world count is outside the supported finite range")
    return rng.sample(_WORLD_LABELS, count)


def _world_count(size: str) -> int:
    if size not in SIZE_LEVELS:
        raise TaskSpecError(f"unknown size level: {size!r}")
    return 3 if size == "compact" else 5


def _fraction_prior(rng: random.Random, worlds: list[str]) -> dict[str, Fraction]:
    weights = [rng.randint(1, 7) for _ in worlds]
    total = sum(weights)
    return {world: Fraction(weight, total) for world, weight in zip(worlds, weights, strict=True)}


def _serialise_prior(prior: Mapping[str, Fraction]) -> dict[str, str]:
    return {world: encode_fraction(probability) for world, probability in prior.items()}


def _prior_from_public(public: Mapping[str, Any]) -> dict[str, Fraction]:
    raw = public.get("prior")
    if type(raw) is not dict or not raw:
        raise TaskSpecError("prior must be a nonempty world-to-fraction object")
    return {world: decode_fraction(value, label=f"prior[{world}]") for world, value in raw.items()}


def _event_from_public(public: Mapping[str, Any], prior: Mapping[str, Fraction]) -> EpistemicEvent:
    raw_event = public.get("event")
    if type(raw_event) is not dict or set(raw_event) != {"name", "likelihoods"}:
        raise TaskSpecError("event must contain exactly name and likelihoods")
    if type(raw_event["name"]) is not str or not raw_event["name"]:
        raise TaskSpecError("event name must be a nonempty string")
    raw_likelihoods = raw_event["likelihoods"]
    if type(raw_likelihoods) is not dict:
        raise TaskSpecError("event likelihoods must be an object")
    likelihoods: dict[str, Any] = {}
    for world, value in raw_likelihoods.items():
        # Preserve unrelated sparse entries exactly: the approved sparse
        # contract ignores them, including values that are not probabilities.
        likelihoods[world] = (
            decode_fraction(value, label=f"likelihood[{world}]") if world in prior else value
        )
    return EpistemicEvent(raw_event["name"], likelihoods)


def _policy_from_public(public: Mapping[str, Any]) -> dict[str, dict[str, Fraction]]:
    raw = public.get("policy")
    if type(raw) is not dict:
        raise TaskSpecError("policy must be a world-to-observation-row object")
    policy: dict[str, dict[str, Fraction]] = {}
    for world, row in raw.items():
        if type(row) is not dict:
            raise TaskSpecError(f"policy[{world}] must be an observation distribution")
        policy[world] = {
            observation: decode_fraction(probability, label=f"policy[{world}][{observation}]")
            for observation, probability in row.items()
        }
    return policy


def _ids_from_world_records(public: Mapping[str, Any]) -> list[str]:
    records = public.get("worlds")
    if type(records) is not list or not records:
        raise TaskSpecError("worlds must be a nonempty array")
    ids: list[str] = []
    for record in records:
        if type(record) is dict and type(record.get("id")) is str and record["id"]:
            ids.append(record["id"])
        elif type(record) is str and record:
            ids.append(record)
        else:
            raise TaskSpecError("each world must be an ID or a record with a nonempty ID")
    if len(set(ids)) != len(ids):
        raise TaskSpecError("world IDs must be unique")
    return ids


def _partition_input(public: Mapping[str, Any], worlds: list[str]) -> dict[str, list[set[str]]]:
    raw = public.get("partitions")
    if type(raw) is not dict:
        raise TaskSpecError("partitions must be an agent-to-cells object")
    partitions: dict[str, list[set[str]]] = {}
    for agent, cells in raw.items():
        if type(agent) is not str or not agent or type(cells) is not list:
            raise TaskSpecError("each agent needs a nonempty ID and an array of cells")
        parsed_cells: list[set[str]] = []
        for cell in cells:
            if type(cell) is not list or any(type(world) is not str for world in cell):
                raise TaskSpecError(f"partition cell for {agent!r} must be an array of world IDs")
            parsed_cells.append(set(cell))
        partitions[agent] = parsed_cells
    # The accepted S5 constructor performs authoritative coverage, overlap,
    # emptiness, and dangling-reference validation.
    return partitions


def propositional_model_from_json(public: Mapping[str, Any]) -> PropositionalModel:
    """Explicit JSON-to-accepted-propositional-S5-model adapter."""
    world_ids = _ids_from_world_records(public)
    raw_partitions = _partition_input(public, world_ids)
    raw_worlds = public["worlds"]
    valuation: dict[str, frozenset[str]] = {}
    for record in raw_worlds:
        if type(record) is str:
            valuation[record] = frozenset()
            continue
        atoms = record.get("valuation")
        if type(atoms) is not list or any(type(name) is not str or not name for name in atoms):
            raise TaskSpecError(
                f"world {record['id']!r} valuation must be an array of proposition names"
            )
        if len(set(atoms)) != len(atoms):
            raise TaskSpecError(f"world {record['id']!r} has duplicate proposition names")
        valuation[record["id"]] = frozenset(atoms)
    partitions = {
        agent: frozenset(frozenset(cell) for cell in cells)
        for agent, cells in raw_partitions.items()
    }
    return PropositionalModel(
        worlds=frozenset(world_ids),
        partitions=partitions,
        valuation=valuation,
    )


def relational_model_from_json(public: Mapping[str, Any]) -> RelationalModel:
    """Explicit JSON adapter for the separate general, non-S5 relation API."""
    records = public.get("worlds")
    if type(records) is not list or not records:
        raise TaskSpecError("worlds must be a nonempty array")
    worlds: list[WorldRecord] = []
    for record in records:
        if type(record) is not dict or set(record) != {"id", "properties"}:
            raise TaskSpecError("relational worlds require exactly id and properties")
        if type(record["properties"]) is not dict:
            raise TaskSpecError("world properties must be an object")
        worlds.append(WorldRecord(record["id"], record["properties"]))
    agents = public.get("agents")
    if type(agents) is not list or any(type(agent) is not str or not agent for agent in agents):
        raise TaskSpecError("agents must be an array of nonempty IDs")
    model = RelationalModel(worlds, agents)
    relations = public.get("relations")
    if type(relations) is not dict or set(relations) != set(agents):
        raise TaskSpecError("relation table must name exactly the declared agents")
    for agent, edges in relations.items():
        if type(edges) is not list:
            raise TaskSpecError(f"relations[{agent}] must be an edge array")
        for edge in edges:
            if type(edge) is not list or len(edge) != 2:
                raise TaskSpecError("each relation edge must contain source and target world IDs")
            model.add_relation(agent, edge[0], edge[1])
    return model


def deterministic_protocol_from_json(
    worlds: list[str], rules: object
) -> dict[str, Callable[[str], bool]]:
    """Snapshot JSON truth tables into pure callable deterministic rules."""
    if type(rules) is not dict:
        raise TaskSpecError("protocol rules must be an object")
    protocol: dict[str, Callable[[str], bool]] = {}
    for agent, row in rules.items():
        if type(agent) is not str or not agent or type(row) is not dict:
            raise TaskSpecError("each protocol rule needs an agent ID and world table")
        if set(row) != set(worlds):
            raise TaskSpecError(f"protocol rule {agent!r} must cover exactly the declared worlds")
        if any(type(decision) is not bool for decision in row.values()):
            raise TaskSpecError("deterministic protocol outputs must be actual Booleans")
        snapshot = MappingProxyType(dict(row))

        def rule(world: str, decisions: Mapping[str, bool] = snapshot) -> bool:
            if world not in decisions:
                raise TaskSpecError(f"protocol evaluated at unknown world: {world}")
            return decisions[world]

        protocol[agent] = rule
    return protocol


def _ordered_worlds(worlds: set[str] | frozenset[str], public: Mapping[str, Any]) -> list[str]:
    order = _ids_from_world_records(public)
    return [world for world in order if world in worlds]


def evaluate_public_task(variant: str, public: Mapping[str, Any]) -> dict[str, Any]:
    """Run the accepted oracle for one public task and serialize exact outputs."""
    if variant not in VARIANT_TITLES:
        raise TaskSpecError(f"unknown task variant: {variant!r}")
    if type(public) is not dict or public.get("variant") != variant:
        raise TaskSpecError("task variant and public task record disagree")

    if variant in {"event_sparse", "event_strict"}:
        prior = _prior_from_public(public)
        event = _event_from_public(public, prior)
        posterior = (
            calculate_posterior_sparse(prior, event)
            if variant == "event_sparse"
            else calculate_posterior_strict(prior, event)
        )
        return {"posterior": {world: encode_fraction(value) for world, value in posterior.items()}}

    if variant in {"policy_sparse", "policy_strict"}:
        prior = _prior_from_public(public)
        policy = _policy_from_public(public)
        observation = public.get("realized_observation")
        if type(observation) is not str or not observation:
            raise TaskSpecError("realized observation must be a nonempty string")
        if variant == "policy_sparse":
            instance = SuppliedPolicyInstance(prior, policy, observation)
        else:
            alphabet = public.get("observation_alphabet")
            if type(alphabet) is not list or any(type(label) is not str for label in alphabet):
                raise TaskSpecError("strict policy needs an observation alphabet array")
            instance = StrictSuppliedPolicyInstance(prior, policy, observation, tuple(alphabet))
        posterior = bayes_update(instance)
        return {"posterior": {world: encode_fraction(value) for world, value in posterior.items()}}

    if variant == "relational_modal":
        model = relational_model_from_json(public)
        query = public.get("query")
        if type(query) is not dict or set(query) != {"agent", "world", "formula"}:
            raise TaskSpecError("relational query requires agent, world, and formula")
        formula = _general_formula_from_json(query["formula"], model)
        result = model.knows(query["agent"], query["world"], formula)
        return {"truth": result}

    if variant == "s5_knowledge":
        model = propositional_model_from_json(public)
        query = public.get("query")
        if type(query) is not dict or set(query) != {"agent", "world", "formula"}:
            raise TaskSpecError("S5 query requires agent, world, and formula")
        formula = formula_from_json(query["formula"])
        result = formula(model, query["world"])

        # Cross-check the separate accepted partition-based S5 interface. This
        # keeps its semantics distinct while verifying adapter equivalence.
        ids = _ids_from_world_records(public)
        records = {record["id"]: record for record in public["worlds"]}
        worlds = [WorldRecord(world, {"valuation": records[world]["valuation"]}) for world in ids]
        direct_s5 = S5EpistemicModel(worlds, _partition_input(public, ids))
        proposition = query["formula"].get("knows", {}).get("formula", {}).get("atom")
        if proposition is None or set(query["formula"]) != {"knows"}:
            raise TaskSpecError("S5 knowledge variant requires knows(agent, atom)")
        direct = direct_s5.knows(
            query["agent"],
            query["world"],
            lambda world: proposition in world.properties["valuation"],
        )
        if result is not direct:
            raise TaskSpecError("S5 serialization adapter disagrees with direct S5 semantics")
        return {"truth": result}

    if variant in {"announcement_unpointed", "announcement_checked"}:
        model = propositional_model_from_json(public)
        raw_sequence = public.get("formula_sequence")
        if type(raw_sequence) is not list:
            raise TaskSpecError("formula_sequence must be an array")
        formulas = [formula_from_json(spec) for spec in raw_sequence]
        if variant == "announcement_unpointed":
            updated = announce_sequence(model, formulas)
            return {"worlds": _ordered_worlds(updated.worlds, public)}
        actual_world = public.get("actual_world")
        try:
            updated = announce_sequence_checked(model, actual_world, formulas)
        except ModelError as exc:
            if str(exc) == "announcement is false at the actual world":
                return {"accepted": False, "worlds": None}
            raise
        return {"accepted": True, "worlds": _ordered_worlds(updated.worlds, public)}

    if variant in {"deterministic_silence", "silence_empty_protocol"}:
        prior = _prior_from_public(public)
        worlds = list(prior)
        protocol = deterministic_protocol_from_json(worlds, public.get("protocol"))
        posterior = update_on_silence(prior, protocol)
        return {"posterior": {world: encode_fraction(value) for world, value in posterior.items()}}

    if variant in {"common_knowledge", "common_knowledge_empty_group"}:
        model = propositional_model_from_json(public)
        group = public.get("group")
        if type(group) is not list or any(type(agent) is not str for agent in group):
            raise TaskSpecError("common-knowledge group must be an array of agent IDs")
        formula = common_knowledge(group, formula_from_json(public.get("formula")))
        return {"truth": formula(model, public.get("actual_world"))}

    if variant in {"information_pool", "information_empty_group"}:
        model = propositional_model_from_json(public)
        actual_world = public.get("actual_world")
        individual_agent = public.get("individual_agent")
        group = public.get("pool_agents")
        if type(individual_agent) is not str or type(group) is not list:
            raise TaskSpecError(
                "information task requires an individual agent and pooled agent array"
            )
        individual = information_set(model, individual_agent, actual_world)
        pooled = joint_information(model, group, actual_world)
        return {
            "individual": _ordered_worlds(individual, public),
            "pooled": _ordered_worlds(pooled, public),
        }

    raise TaskSpecError(f"no oracle for variant: {variant!r}")


def validate_answer(variant: str, answer: object, public: Mapping[str, Any]) -> list[str]:
    """Validate exact answer keys, primitive types, and rational encoding."""
    errors: list[str] = []
    if type(answer) is not dict:
        return ["ANSWER must be a literal dictionary"]

    keys_by_variant = {
        "event_sparse": {"posterior"},
        "event_strict": {"posterior"},
        "policy_sparse": {"posterior"},
        "policy_strict": {"posterior"},
        "deterministic_silence": {"posterior"},
        "silence_empty_protocol": {"posterior"},
        "relational_modal": {"truth"},
        "s5_knowledge": {"truth"},
        "common_knowledge": {"truth"},
        "common_knowledge_empty_group": {"truth"},
        "announcement_unpointed": {"worlds"},
        "announcement_checked": {"accepted", "worlds"},
        "information_pool": {"individual", "pooled"},
        "information_empty_group": {"individual", "pooled"},
    }
    expected_keys = keys_by_variant.get(variant)
    if expected_keys is None:
        return [f"unsupported variant {variant!r}"]
    if set(answer) != expected_keys:
        errors.append(f"ANSWER keys must be exactly {sorted(expected_keys)}")
        return errors

    if "posterior" in expected_keys:
        posterior = answer["posterior"]
        try:
            prior_worlds = set(_prior_from_public(public))
        except (TaskSpecError, SpecError) as exc:
            return [f"public prior invalid: {exc}"]
        if type(posterior) is not dict or set(posterior) != prior_worlds:
            errors.append("posterior must cover exactly the prior worlds")
        else:
            exact_values: list[Fraction] = []
            for world, value in posterior.items():
                try:
                    exact = decode_fraction(value, label=f"posterior[{world}]")
                    if exact < 0:
                        errors.append(f"posterior[{world}] must be nonnegative")
                    exact_values.append(exact)
                except TaskSpecError as exc:
                    errors.append(str(exc))
            if len(exact_values) == len(posterior) and sum(exact_values, Fraction(0)) != 1:
                errors.append("posterior probabilities must sum exactly to one")
    elif "truth" in expected_keys:
        if type(answer["truth"]) is not bool:
            errors.append("truth must be an actual Boolean")
    elif variant == "announcement_unpointed":
        errors.extend(_validate_world_list(answer["worlds"], public, "worlds", allow_none=False))
    elif variant == "announcement_checked":
        if type(answer["accepted"]) is not bool:
            errors.append("accepted must be an actual Boolean")
        if answer["accepted"]:
            errors.extend(
                _validate_world_list(answer["worlds"], public, "worlds", allow_none=False)
            )
            if type(public.get("actual_world")) is str and answer["worlds"] is not None:
                if public["actual_world"] not in answer["worlds"]:
                    errors.append("accepted checked sequence must retain the actual world")
        elif answer["worlds"] is not None:
            errors.append("rejected checked sequence must use worlds: None")
    else:
        for key in ("individual", "pooled"):
            errors.extend(_validate_world_list(answer[key], public, key, allow_none=False))
    return errors


def _validate_world_list(
    value: object, public: Mapping[str, Any], label: str, *, allow_none: bool
) -> list[str]:
    if value is None and allow_none:
        return []
    if type(value) is not list or any(type(world) is not str for world in value):
        return [f"{label} must be an array of world IDs"]
    known = set(_ids_from_world_records(public))
    if len(value) != len(set(value)):
        return [f"{label} must not contain duplicate world IDs"]
    if not set(value) <= known:
        return [f"{label} contains an unknown world ID"]
    return []


def _draw_partitions(worlds: list[str], *, offset: int = 0) -> list[list[str]]:
    cells: list[list[str]] = []
    index = offset
    while index < len(worlds):
        cells.append(worlds[index : index + 2])
        index += 2
    return cells


def _chain_partitions(worlds: list[str]) -> dict[str, list[list[str]]]:
    a_cells = _draw_partitions(worlds, offset=0)
    b_cells: list[list[str]] = [[worlds[0]]]
    b_cells.extend(_draw_partitions(worlds, offset=1))
    return {"A": a_cells, "B": b_cells}


def _announce_public(rng: random.Random, worlds: list[str], variant: str) -> dict[str, Any]:
    cells = _chain_partitions(worlds)
    valuation: dict[str, list[str]] = {}
    for index, world in enumerate(worlds):
        if index == 0:
            valuation[world] = ["p", "q"]
        elif index == 1:
            valuation[world] = ["p"]
        elif index == 2:
            valuation[world] = ["q"]
        else:
            valuation[world] = ["p", "q"] if index % 2 == 0 else ["q"]
    atom_p = {"atom": "p"}
    knows_b_p = {"knows": {"agent": "B", "formula": atom_p}}
    sequence = [atom_p, knows_b_p]
    if rng.choice((False, True)):
        sequence.reverse()
    public: dict[str, Any] = {
        "variant": variant,
        "worlds": [{"id": world, "valuation": valuation[world]} for world in worlds],
        "partitions": cells,
        "formula_sequence": sequence,
    }
    if variant == "announcement_checked":
        # The second announcement is true at this actual world only after the
        # first restriction in forward order; reversing the order is rejected.
        public["actual_world"] = worlds[1]
    return public


def _binary_information_public(worlds: list[str], variant: str, seed: int) -> dict[str, Any]:
    bit_count = 2 if len(worlds) == 4 else 3
    agent_names = ["A", "B", "C"][:bit_count]
    partitions: dict[str, list[list[str]]] = {}
    for bit, agent in enumerate(agent_names):
        cells: dict[int, list[str]] = {}
        for index, world in enumerate(worlds):
            key = (index >> (bit_count - bit - 1)) & 1
            cells.setdefault(key, []).append(world)
        partitions[agent] = list(cells.values())
    actual_world = worlds[seed % len(worlds)]
    empty_group = variant == "information_empty_group"
    return {
        "variant": variant,
        "worlds": [
            {"id": world, "valuation": ["p"] if index == 0 else []}
            for index, world in enumerate(worlds)
        ],
        "partitions": partitions,
        "actual_world": actual_world,
        "individual_agent": "A",
        "pool_agents": [] if empty_group else agent_names,
    }


def _make_public(variant: str, size: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    count = _world_count(size)

    if variant in {"event_sparse", "event_strict"}:
        worlds = _world_ids(rng, count)
        prior = _fraction_prior(rng, worlds)
        if variant == "event_sparse":
            omitted = rng.choice(worlds)
            choices = (Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(1, 4))
            likelihoods = {
                world: encode_fraction(rng.choice(choices)) for world in worlds if world != omitted
            }
            # An unrelated malformed value proves that sparse semantics ignore
            # extras instead of accidentally validating them as model states.
            likelihoods["outside_model"] = "ignored by sparse contract"
        else:
            choices = (Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(1, 4))
            likelihoods = {world: encode_fraction(rng.choice(choices)) for world in worlds}
        return {
            "variant": variant,
            "contract": "sparse" if variant == "event_sparse" else "strict",
            "prior": _serialise_prior(prior),
            "event": {"name": "observed_signal", "likelihoods": likelihoods},
        }

    if variant in {"policy_sparse", "policy_strict"}:
        worlds = _world_ids(rng, count)
        prior = _fraction_prior(rng, worlds)
        if variant == "policy_sparse":
            sparse_rows = (
                {"signal": Fraction(2, 3), "quiet": Fraction(1, 3)},
                {"quiet": Fraction(1)},
                {"signal": Fraction(1, 4), "quiet": Fraction(3, 4)},
                {"other": Fraction(1, 2), "quiet": Fraction(1, 2)},
            )
            policy = {
                world: {
                    label: encode_fraction(probability)
                    for label, probability in sparse_rows[(index + seed) % len(sparse_rows)].items()
                }
                for index, world in enumerate(worlds)
            }
            return {
                "variant": variant,
                "contract": "sparse_full_policy",
                "prior": _serialise_prior(prior),
                "policy": policy,
                "realized_observation": "signal",
            }
        alphabet = ["signal", "quiet", "other"]
        patterns = ((1, 2, 1), (0, 3, 1), (2, 0, 2), (1, 1, 2))
        policy = {}
        for index, world in enumerate(worlds):
            weights = patterns[(index + seed) % len(patterns)]
            total = sum(weights)
            policy[world] = {
                observation: encode_fraction(Fraction(weight, total))
                for observation, weight in zip(alphabet, weights, strict=True)
            }
        return {
            "variant": variant,
            "contract": "strict_full_policy",
            "prior": _serialise_prior(prior),
            "policy": policy,
            "observation_alphabet": alphabet,
            "realized_observation": "signal",
        }

    if variant == "relational_modal":
        worlds = _world_ids(rng, count)
        actual_index = seed % count
        actual = worlds[actual_index]
        records = [{"id": world, "properties": {"p": bool(rng.getrandbits(1))}} for world in worlds]
        edges_a: list[list[str]] = []
        mode = seed % 3
        if mode == 1:
            edges_a.append([actual, worlds[(actual_index + 1) % count]])
            if count > 2:
                edges_a.append(
                    [worlds[(actual_index + 1) % count], worlds[(actual_index + 2) % count]]
                )
        elif mode == 2:
            edges_a.extend([[actual, actual], [actual, worlds[(actual_index + 1) % count]]])
        # mode zero deliberately leaves A's accessibility empty at the actual
        # world. General modal semantics makes universal knowledge vacuously true.
        edges_b = [[worlds[index], worlds[(index + 1) % count]] for index in range(count - 1)]
        return {
            "variant": variant,
            "frame": "general_relation_not_implicitly_s5",
            "worlds": records,
            "agents": ["A", "B"],
            "relations": {"A": edges_a, "B": edges_b},
            "query": {"agent": "A", "world": actual, "formula": {"atom": "p"}},
        }

    if variant == "s5_knowledge":
        worlds = _world_ids(rng, count)
        pivot = 1 if count > 2 else 0
        cell = [worlds[0], worlds[pivot]]
        cells = [cell] + [[world] for world in worlds if world not in cell]
        valuation = {world: (["p"] if rng.choice((False, True)) else []) for world in worlds}
        return {
            "variant": variant,
            "worlds": [{"id": world, "valuation": valuation[world]} for world in worlds],
            "partitions": {"A": cells, "B": [[world] for world in worlds]},
            "query": {
                "agent": "A",
                "world": worlds[0],
                "formula": {"knows": {"agent": "A", "formula": {"atom": "p"}}},
            },
        }

    if variant in {"announcement_unpointed", "announcement_checked"}:
        announcement_worlds = _world_ids(rng, count)
        return _announce_public(rng, announcement_worlds, variant)

    if variant in {"deterministic_silence", "silence_empty_protocol"}:
        worlds = _world_ids(rng, count)
        prior = _fraction_prior(rng, worlds)
        if variant == "silence_empty_protocol":
            protocol: dict[str, dict[str, bool]] = {}
        else:
            protocol = {
                "A": {world: index == 1 for index, world in enumerate(worlds)},
                "B": {world: index == 2 for index, world in enumerate(worlds)},
            }
        return {
            "variant": variant,
            "prior": _serialise_prior(prior),
            "protocol": protocol,
            "observation": "silence",
        }

    if variant in {"common_knowledge", "common_knowledge_empty_group"}:
        n = 5 if size == "compact" else 7
        worlds = _world_ids(rng, n)
        partitions = _chain_partitions(worlds)
        valuation = {world: (["p"] if index < n - 1 else []) for index, world in enumerate(worlds)}
        group = [] if variant == "common_knowledge_empty_group" else ["A", "B"]
        return {
            "variant": variant,
            "worlds": [{"id": world, "valuation": valuation[world]} for world in worlds],
            "partitions": partitions,
            "actual_world": worlds[0],
            "group": group,
            "formula": {"atom": "p"},
            "closure_note": "full finite reachability over the selected relations",
        }

    if variant in {"information_pool", "information_empty_group"}:
        n = 4 if size == "compact" else 8
        worlds = _world_ids(rng, n)
        return _binary_information_public(worlds, variant, seed)

    raise TaskSpecError(f"unknown task variant: {variant!r}")


def _answer_template(variant: str, public: Mapping[str, Any]) -> dict[str, Any]:
    if variant in {
        "event_sparse",
        "event_strict",
        "policy_sparse",
        "policy_strict",
        "deterministic_silence",
        "silence_empty_protocol",
    }:
        prior_worlds = list(public["prior"])
        uniform = encode_fraction(Fraction(1, len(prior_worlds)))
        return {"posterior": dict.fromkeys(prior_worlds, uniform)}
    if variant in {
        "relational_modal",
        "s5_knowledge",
        "common_knowledge",
        "common_knowledge_empty_group",
    }:
        return {"truth": False}
    if variant == "announcement_unpointed":
        return {"worlds": []}
    if variant == "announcement_checked":
        return {"accepted": False, "worlds": None}
    if variant in {"information_pool", "information_empty_group"}:
        return {"individual": [], "pooled": []}
    raise TaskSpecError(f"no answer template for variant: {variant!r}")


def build_instance(variant: str, size: str, seed: int) -> dict[str, Any]:
    """Build one reproducible finite instance and its hidden exact oracle."""
    if variant not in VARIANT_TITLES:
        raise TaskSpecError(f"unknown task variant: {variant!r}")
    if size not in SIZE_LEVELS:
        raise TaskSpecError(f"unknown size level: {size!r}")
    if type(seed) is not int:
        raise TaskSpecError("seed must be an integer (not a Boolean)")
    public = _make_public(variant, size, seed)
    answer = evaluate_public_task(variant, public)
    return {
        "schema_version": 1,
        "variant": variant,
        "size": size,
        "seed": seed,
        "public": public,
        "expected_answer": answer,
    }


def answer_guide(variant: str, public: Mapping[str, Any]) -> str:
    """Learner-facing answer and semantic contract for the selected task."""
    descriptions = {
        "event_sparse": (
            "Use the named-event sparse contract: a missing prior-world likelihood is zero; "
            "entries for worlds outside the prior are ignored. This is event likelihood data, "
            "not a supplied observation policy."
        ),
        "event_strict": (
            "Use the named-event strict contract: the likelihood table must cover exactly the "
            "prior worlds. This is event likelihood data, not a supplied observation policy."
        ),
        "policy_sparse": (
            "Use each supplied row as a normalized full observation distribution. A label missing "
            "from a row has probability zero; do not reinterpret the table as event-only input."
        ),
        "policy_strict": (
            "Use each normalized full-policy row over the declared observation alphabet. Every row "
            "includes every declared label, including explicit zero probabilities."
        ),
        "relational_modal": (
            "Evaluate universal knowledge over exactly the listed outgoing relation edges. This is "
            "a general relation, not an S5 partition; an empty outgoing set makes the universal "
            "claim vacuously true."
        ),
        "s5_knowledge": (
            "Evaluate the callable propositional knowledge formula in the validated S5 partition "
            "model. Partition cells cover the world set, so the actual world is accessible."
        ),
        "announcement_unpointed": (
            "Apply the announcements in order, reevaluating each formula in the current restricted "
            "model. This operation is unpointed: there is no actual-world truth check. Return the "
            "surviving world IDs."
        ),
        "announcement_checked": (
            "Apply the checked sequence in order, reevaluating each formula in the current model. "
            "Each announcement must be true at the supplied actual world. Return accepted=false "
            "and worlds=None if a step is false there; otherwise return the final worlds."
        ),
        "deterministic_silence": (
            "Each listed rule is a deterministic Boolean announcement decision. Silence means no "
            "rule fires; all rules are evaluated. Update the exact prior using that likelihood."
        ),
        "silence_empty_protocol": (
            "The protocol is empty, so no rule can announce and silence is guaranteed. Preserve the "
            "prior exactly; do not invent probabilistic-agent or independence assumptions."
        ),
        "common_knowledge": (
            "Check common knowledge by full finite reachability closure under the union of the "
            "selected S5 relations; do not approximate it with a fixed nesting depth."
        ),
        "common_knowledge_empty_group": (
            "The selected group is empty. Its reachability closure contains only the starting world, "
            "so evaluate the formula there."
        ),
        "information_pool": (
            "Return the named agent's individual information set and the intersection of all listed "
            "agents' cells at the actual world. Pooled information is not communication or common knowledge."
        ),
        "information_empty_group": (
            "Return the named agent's individual information set. The pooled group is empty, so its "
            "intersection is the full world set; this is not communication or common knowledge."
        ),
    }
    return (
        f"Task variant: {VARIANT_TITLES[variant]}.\n\n"
        f"{descriptions[variant]}\n\n"
        f"Read `task.json` for the complete learner-visible finite instance. Edit only `answer.py` "
        "and assign the requested literal dictionary to `ANSWER`. Posterior values must be exact, "
        "reduced rational strings such as `2/5`; do not use floats. For world lists, use the order "
        "in `task.json`. Run `python visible_tests.py` before submitting."
    )


def instance_spec(variant: str, size: str, seed: int) -> dict[str, Any]:
    """Public renderer entry point; includes the hidden answer only for the judge image."""
    return build_instance(variant, size, seed)


def answer_template(variant: str, public: Mapping[str, Any]) -> dict[str, Any]:
    """Return an empty, schema-shaped answer starter without revealing the oracle."""
    return _answer_template(variant, public)


__all__ = [
    "SIZE_LEVELS",
    "TaskSpecError",
    "VARIANT_TITLES",
    "answer_guide",
    "answer_template",
    "build_instance",
    "decode_fraction",
    "encode_fraction",
    "evaluate_public_task",
    "formula_from_json",
    "instance_spec",
    "propositional_model_from_json",
    "relational_model_from_json",
    "serialize_formula",
    "validate_answer",
]
