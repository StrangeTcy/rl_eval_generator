# Distributed Physical Topology Constraint Sync

Your task is to implement a topologically aware load balancer in `route.py` for distributed sequence/gradient communication.

In distributed GPU clusters, multiple nodes exchange gradients across overlapping local switches. To prevent switch saturation, the communication routing must be strictly bounded by the physical capacity of the switches.

Complete `%%MODEL_CLASS%%.allocate_bandwidth` for nonnegative demands on `route_A`, `route_B`, and `route_C`. Missing routes have zero demand. Every pair overlaps a switch: A+B, A+C, and B+C must each be at most `local_capacity`. The total must be at most `global_capacity`, and allocations must be nonnegative and no greater than demand.

Use clipped-demand proportional allocation: first clip each route's demand to `local_capacity`, then multiply all clipped demands by the largest common scale in `[0, 1]` satisfying every pair limit and the global limit. This preserves equal-demand symmetry and uses the maximum feasible bandwidth under that proportional objective. For demands `(120, 60, 0)` with local capacity 100 and a nonbinding global limit, the result is `(62.5, 37.5, 0)`.

Capacity feasibility and the proportional allocation objective are checked separately.
