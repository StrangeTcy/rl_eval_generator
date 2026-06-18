# Distributed Physical Topology Constraint Sync

Your task is to implement a topologically aware load balancer in `route.py` for distributed sequence/gradient communication.

In distributed GPU clusters, multiple nodes exchange gradients across overlapping local switches. To prevent switch saturation, the communication routing must be strictly bounded by the physical capacity of the switches.

The task is to complete the `%%MODEL_CLASS%%` class in `route.py` to implement a bandwidth routing function:
- It allocates bandwidth across Node 1, Node 2, and Node 3.
- It must ensure that the sum of the allocated bandwidth across all active routes does not exceed the aggregate limit of the central backbone router under high traffic demands.

The current implementation in `route.py` runs and allocates local node bandwidth correctly, but overflows the global capacity limit of the main backbone router during concurrent communication loops. Correct the load balancing logic to scale routing paths safely.
