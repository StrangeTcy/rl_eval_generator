class %%MODEL_CLASS%%:
    def __init__(self, local_capacity: float = 100.0, global_capacity: float = %%GLOBAL_CAP%%):
        self.local_capacity = local_capacity
        self.global_capacity = global_capacity

    def allocate_bandwidth(self, demands: dict[str, float]) -> dict[str, float]:
        # BUG: Naively allocates bandwidth up to the local switch capacity (local_capacity)
        # for each node-pair individually, ignoring the global backbone capacity limit (global_capacity).
        # This causes the aggregate sum of all paths to overload the main router.
        allocations = {}
        for path, demand in demands.items():
            allocations[path] = min(demand, self.local_capacity)
        return allocations
