"""Nested situation evaluator.

Each frame lists worlds, atoms, and per-agent indistinguishability blocks.
A query is an atom, a Boolean combination, or K_agent formula. A bundle is a
proposed local cell per agent. This baseline treats every bundle as possible
and treats K as transparent, which is incorrect in general.
"""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        """Return query truth and, if present, bundle possibility.

        {"query_value": bool, "bundle_possible": bool}  # bundle key omitted when both bundles are null
        """
        actual = tuple(instance["actual"])
        frames = instance["frames"]
        levels = instance["levels"]

        def atom_here(atom):
            for world, level in zip(actual, levels):
                if world in frames[level]["atoms"].get(atom, []):
                    return True
            return False

        def peel(formula):
            if isinstance(formula, str):
                return atom_here(formula)
            if isinstance(formula, list) and formula and formula[0] == "not":
                return not peel(formula[1])
            if isinstance(formula, list) and formula and formula[0] == "and":
                return peel(formula[1]) and peel(formula[2])
            if isinstance(formula, list) and formula and formula[0] == "K":
                return peel(formula[2])
            return False

        out = {"query_value": bool(peel(instance["query"]))}
        if instance.get("bundle") is not None or instance.get("nested_bundle") is not None:
            out["bundle_possible"] = True
        return out
