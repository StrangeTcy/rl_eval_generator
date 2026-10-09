"""CS011 fragmented observation: design and result accepted by the user."""
from .epistemic_relations import S5EpistemicModel, World as WorldRecord
from .public_announcements import Agent, EpistemicModel, ModelError, World


def validate_partition(worlds: frozenset[World], classes: frozenset[frozenset]) -> None:
    """Preserve source API using the accepted S5 frame validator."""
    S5EpistemicModel([WorldRecord(w, {}) for w in worlds], {'partition': classes})


def information_set(model: EpistemicModel, agent: Agent,
                    true_world: World) -> frozenset[World]:
    if true_world not in model.worlds:
        raise ModelError(f'unknown world: {true_world}')
    if agent not in model.partitions:
        raise ModelError(f'unknown agent: {agent}')
    validate_partition(model.worlds, model.partitions[agent])
    return model.agent_class(agent, true_world)


def joint_information(model: EpistemicModel, agents: list[Agent],
                      true_world: World) -> frozenset[World]:
    """Pooled/distributed information: intersection of selected observation cells.

    This does not implement communication or establish individual or common
    knowledge. With no observations, all model worlds remain possible. Duplicate
    agents are harmless. The actual world must exist even for an empty group.
    """
    if true_world not in model.worlds:
        raise ModelError(f'unknown world: {true_world}')
    sets = [information_set(model, agent, true_world) for agent in agents]
    out = model.worlds
    for cell in sets:
        out = out & cell
    return out
