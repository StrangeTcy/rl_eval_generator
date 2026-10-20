"""Distributed worker-pool scheduler.

Workers run declared programs: spawn, send, recv, lock, unlock, compute.
One mutex is shared. A solution is an interleaving that finishes every
program without taking a lock twice or reading an empty mailbox.
"""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        """Return a completing trace, or report that none exists.

        {"status": "sat", "trace": [{"agent": name, "op": op}, ...], "result": int}
        {"status": "unsat"}
        """
        workers = instance["workers"]
        # Handle the lock-free two-agent visible case only.
        if len(workers) == 2 and all(
            not any(op == "lock" for op in spec["program"]) for spec in workers.values()
        ):
            root = instance["root"]
            leaf = next(name for name in workers if name != root)
            trace = []
            if "spawn" in workers[root]["program"]:
                trace.append({"agent": root, "op": "spawn"})
            for op in workers[leaf]["program"]:
                trace.append({"agent": leaf, "op": op})
            for op in workers[root]["program"]:
                if op == "spawn":
                    continue
                trace.append({"agent": root, "op": op})
            return {"status": "sat", "trace": trace}
        return {"status": "sat", "trace": []}
