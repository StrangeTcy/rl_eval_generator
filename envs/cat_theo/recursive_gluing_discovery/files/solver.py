"""Chart-assembly solver.

A network is assembled from copies of a small gadget. Each region has a finite
domain and a local cycle of those states. Some overlaps list a few compatible
pairs; some list none. A global assignment picks one state per region, or the
solver reports that none exists.
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

        # Use listed pairs only. Nested copies (ids containing "/") are solved
        # per depth; empty pair lists and local cycles are ignored.
        adj = defaultdict(list)
        for overlap in overlaps:
            pairs = overlap.get("pairs") or []
            if not pairs:
                continue
            left = overlap["left"]
            right = overlap["right"]
            if left.count("/") != right.count("/"):
                continue
            fwd = defaultdict(list)
            rev = defaultdict(list)
            for a, b in pairs:
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
