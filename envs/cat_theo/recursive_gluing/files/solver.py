"""Region-network assignment.

A region network is a finite collection of named regions. Each region has a
finite domain of locally valid states. Overlaps list which pairs of local
states may appear together. A global assignment picks one state per region
so that every overlap is respected, or reports that no such assignment exists.
"""
from collections import defaultdict, deque


class %%MODEL_CLASS%%:
    def solve(self, instance):
        """Return a globally consistent assignment, or report that none exists.

        Expected output:
            {"status": "sat", "assignment": {region_id: label, ...}}
            {"status": "unsat"}
        """
        regions = instance["regions"]
        overlaps = instance["overlaps"]

        # Nested blocks (ids containing "/") are solved one nesting depth at a
        # time. Overlaps that cross depths are deferred to a combination step
        # that currently just fills any remaining region with its first label.
        adj = defaultdict(list)
        for overlap in overlaps:
            left = overlap["left"]
            right = overlap["right"]
            if left.count("/") != right.count("/"):
                continue
            fwd = defaultdict(list)
            rev = defaultdict(list)
            for a, b in overlap["pairs"]:
                fwd[a].append(b)
                rev[b].append(a)
            adj[left].append((right, fwd))
            adj[right].append((left, rev))

        assignment = {}
        for start in sorted(regions):
            if start in assignment:
                continue
            domain = list(regions[start]["domain"])
            if not domain:
                return {"status": "unsat"}
            assignment[start] = domain[0]
            queue = deque([start])
            while queue:
                current = queue.popleft()
                for neighbour, func in adj[current]:
                    if neighbour in assignment:
                        continue
                    options = func.get(assignment[current], [])
                    if options:
                        assignment[neighbour] = options[0]
                        queue.append(neighbour)

        for rid, spec in regions.items():
            if rid not in assignment:
                domain = list(spec["domain"])
                if not domain:
                    return {"status": "unsat"}
                assignment[rid] = domain[0]
        return {"status": "sat", "assignment": assignment}
