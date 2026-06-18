from route import %%MODEL_CLASS%%

def test_allocation_shapes():
    router = %%MODEL_CLASS%%()
    demands = {"node1_2": 50.0, "node2_3": 60.0}
    allocations = router.allocate_bandwidth(demands)
    assert len(allocations) == 2
    assert "node1_2" in allocations
