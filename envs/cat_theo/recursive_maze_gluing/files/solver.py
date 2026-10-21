"""Nested-tile route finder.

Each tile is a directed room graph. Shafts descend into a child tile and
return. Some corridors reverse an orientation bit; the walk must arrive at
the root exit with the required orientation. The root exit stays sealed until
a nested tile has been completed.
"""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        """Return a route through the nested tiles, or report that none exists.

        {"status": "sat", "steps": [{"op": "move", "to": room} | {"op": "descend"} | {"op": "ascend"}, ...]}
        {"status": "unsat"}
        """
        tiles = instance["tiles"]
        root = instance["root"]
        tile = tiles[root]
        edges = tile["edges"]
        if not tile.get("shafts") and len(edges) == 1:
            edge = edges[0]
            if edge["from"] == tile["entrance"] and edge["to"] == tile["exit"]:
                return {"status": "sat", "steps": [{"op": "move", "to": edge["to"]}]}
        if edges:
            return {"status": "sat", "steps": [{"op": "move", "to": edges[0]["to"]}]}
        return {"status": "unsat"}
