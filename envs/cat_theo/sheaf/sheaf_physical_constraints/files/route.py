class %%MODEL_CLASS%%:
    def __init__(self, local_capacity: float = 100.0, global_capacity: float = %%GLOBAL_CAP%%):
        self.local_capacity = local_capacity
        self.global_capacity = global_capacity

    def allocate_bandwidth(self, demands: dict[str, float]) -> dict[str, float]:
        # Demands are mapped over three overlapping paths: "route_A", "route_B", and "route_C".
        # Symmetries and overlapping topologies:
        # - Switch S1 is shared by: route_A + route_C (capacity <= local_capacity)
        # - Switch S2 is shared by: route_A + route_B (capacity <= local_capacity)
        # - Switch S3 is shared by: route_B + route_C (capacity <= local_capacity)
        #
        # BUG: Naive allocator that only checks local individual route demands,
        # ignoring the overlapping shared switch constraints and the global backbone capacity.
        allocations = {}
        for path, demand in demands.items():
            allocations[path] = min(demand, self.local_capacity)
        return allocations
