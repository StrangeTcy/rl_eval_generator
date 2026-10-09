"""CS009 callable common knowledge: design and result accepted by the user."""
from .public_announcements import Agent, EpistemicModel, Formula, ModelError, World


def common_knowledge(agents: list[Agent], f: Formula) -> Formula:
    """Check f on reflexive reachability under the union of selected relations.

    Snapshot the selected group; duplicates are harmless and retained. The
    empty group reaches only the starting world, so evaluates f there. Each
    evaluation recomputes closure in its supplied model (no depth cutoff or
    cross-model cache). Callbacks have the accepted pure Boolean contract.
    """
    selected_agents = tuple(agents)

    def holds(m: EpistemicModel, w: World) -> bool:
        if w not in m.worlds:
            raise ModelError(f'unknown world: {w}')
        for agent in selected_agents:
            if agent not in m.partitions:
                raise ModelError(f'unknown agent: {agent}')
        reachable = {w}
        frontier = {w}
        while frontier:
            nxt = set()
            for u in frontier:
                for agent in selected_agents:
                    nxt |= set(m.agent_class(agent, u))
            nxt -= reachable
            reachable |= nxt
            frontier = nxt
        return all(f(m, w2) for w2 in reachable)

    return holds
