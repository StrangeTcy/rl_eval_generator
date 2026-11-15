# Distributed Physical Topology Constraint Sync

Your task is to implement a topologically aware load balancer in `route.py` for distributed sequence/gradient communication.

In distributed GPU clusters, multiple nodes exchange gradients across overlapping local switches. To prevent switch saturation, the communication routing must be strictly bounded by the physical capacity of the switches.

The task is to complete the `%%MODEL_CLASS%%` class in `route.py` to implement a bandwidth routing function:
- It allocates bandwidth across Node 1, Node 2, and Node 3.
- It must ensure that the sum of the allocated bandwidth across all active routes does not exceed the aggregate limit of the central backbone router under high traffic demands.

Use the three routes and switch incidences documented in `route.py`. Demands and capacities are nonnegative. First clip each demand to the individual local capacity. Then multiply all three clipped demands by the same largest scale in `[0, 1]` that satisfies every pairwise switch capacity and the backbone capacity. A zero total demand produces zero allocations. This defines clipped-demand proportional allocation, preserves equal-demand symmetry, and uses the greatest feasible common scale. For example, demands `(120, 60, 0)` with local capacity 100 and backbone capacity at least 100 yield `(62.5, 37.5, 0)`.

Return exactly the input route keys. The judge reports capacity feasibility separately from agreement with this allocation policy. Correct the implementation to satisfy both requirements independently of input key order.
