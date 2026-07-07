from %%MODEL_FILE%% import %%MODEL_CLASS%%

def verify_workflow(deps: dict[int, list[int]], wf: dict[str, dict]) -> bool:
    for job_id, parents in deps.items():
        name = f"job_{job_id}"
        if name not in wf:
            raise AssertionError(f"Missing job {name} in workflow")
        spec = wf[name]
        needs = set(spec.get("needs", []))
        expected_needs = {f"job_{p}" for p in parents}
        if needs != expected_needs:
            raise AssertionError(f"Job {name} needs {needs}, expected {expected_needs}")
        
        layer = spec.get("env", {}).get("LAYER")
        if layer is None:
            raise AssertionError(f"Job {name} missing LAYER in env")
            
        if not parents:
            if layer != 0:
                raise AssertionError(f"Root job {name} has LAYER={layer}, expected 0")
        else:
            max_parent = max(wf[f"job_{p}"]["env"]["LAYER"] for p in parents)
            if layer != max_parent + 1:
                raise AssertionError(f"Job {name} has LAYER={layer}, expected {max_parent + 1}")
    return True

def test_visible():
    engine = %%MODEL_CLASS%%()
    deps = {
        1: [],
        2: [1],
        3: [1],
        4: [2, 3]
    }
    wf = engine.generate_workflow(deps)
    verify_workflow(deps, wf)
    print("Visible tests passed!")

if __name__ == "__main__":
    test_visible()
