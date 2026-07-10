#!/usr/bin/env python3
"""
Scoring calibration tool.

Runs each environment across all difficulty levels with known solutions
and produces calibration curves. This helps researchers interpret scores
and enables meaningful cross-environment comparison.

Usage:
    python tools/calibrate.py --env glyph --output calibration_results.json
    python tools/calibrate.py --all --output all_calibration.json
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

# Known solution patches for each environment
# These should be paths to patch files in the examples/ directory
KNOWN_SOLUTIONS: Dict[str, str] = {
    "glyph": "examples/glyph_solution.patch",
    "batchnorm_ema": "examples/batchnorm_ema_solution.patch",
    "moco": "examples/moco_solution.patch",
    "rope": "examples/rope_hard_solution.patch",
}


def get_env_axes(env_name: str) -> List[Dict]:
    """Get axis definitions for an environment."""
    import yaml
    config_path = ROOT / "envs" / env_name / "config.yaml"
    if not config_path.exists():
        config_path = ROOT / "envs" / "cat_theo" / env_name / "config.yaml"
    if not config_path.exists():
        config_path = ROOT / "envs" / "weird_machine" / env_name / "config.yaml"
    
    with config_path.open() as f:
        config = yaml.safe_load(f)
    return config.get("axes", [])


def generate_all_difficulty_combinations(env_name: str) -> List[Dict[str, str]]:
    """Generate all possible difficulty combinations for an environment."""
    axes = get_env_axes(env_name)
    if not axes:
        return []
    
    # Get all level options for each axis
    axis_options = []
    for ax in axes:
        axis_options.append(list(ax["levels"].keys()))
    
    # Generate all combinations
    from itertools import product
    combinations = []
    for combo in product(*axis_options):
        combinations.append({ax["id"]: level for ax, level in zip(axes, combo)})
    
    return combinations


def run_environment(env_name: str, difficulty: Dict[str, str], seed: int, 
                    patch_path: Optional[str] = None) -> Optional[Dict]:
    """Run an environment and return the judge result.
    
    Returns None if the run fails.
    """
    name = f"calib_{env_name}_{seed}"
    env_dir = ROOT / name
    
    # Clean up
    if env_dir.exists():
        subprocess.run(["rm", "-rf", str(env_dir)], check=False)
    
    # Generate environment
    diff_str = ",".join(difficulty[ax["id"]] for ax in get_env_axes(env_name))
    result = subprocess.run([
        sys.executable, "generate_env.py", "--env", env_name,
        "--name", name, "--difficulty", diff_str, "--seed", str(seed)
    ], cwd=ROOT, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Failed to generate {env_name}: {result.stderr}")
        return None
    
    # Apply patch if provided
    if patch_path and os.path.exists(patch_path):
        # Copy patch to agent workspace
        patch_dest = env_dir / "agent" / "workspace" / "agent.patch"
        patch_dest.parent.mkdir(parents=True, exist_ok=True)
        with open(patch_path) as src, open(patch_dest, "w") as dst:
            dst.write(src.read())
    
    # Run the judge (simplified - in practice this requires Docker)
    # For calibration purposes, we can at least verify the environment generates
    # A full calibration run would require Docker and is beyond this script
    
    # For now, just return metadata about the run
    return {
        "environment": env_name,
        "difficulty": difficulty,
        "seed": seed,
        "patch_applied": patch_path is not None,
        "generated_successfully": True,
    }


def calibrate_environment(env_name: str, seeds: List[int] = [42, 123, 456]) -> Dict:
    """Calibrate a single environment across all difficulty levels and seeds."""
    axes = get_env_axes(env_name)
    results = []
    
    # For calibration, we test with easy difficulty to get baseline scores
    # and hard difficulty to see the range
    test_difficulties = [
        {ax["id"]: "easy" for ax in axes},
        {ax["id"]: "hard" for ax in axes},
    ]
    
    # If there are only 2 axes, also test medium
    if len(axes) <= 2:
        test_difficulties.append({ax["id"]: "medium" for ax in axes})
    
    patch_path = KNOWN_SOLUTIONS.get(env_name)
    
    for difficulty in test_difficulties:
        for seed in seeds:
            result = run_environment(env_name, difficulty, seed, patch_path)
            if result:
                results.append(result)
    
    return {
        "environment": env_name,
        "axes": [ax["id"] for ax in axes],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate scoring across environments."
    )
    parser.add_argument("--env", help="Environment to calibrate")
    parser.add_argument("--all", action="store_true", help="Calibrate all environments")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 123, 456],
                        help="Seeds to use for calibration")
    parser.add_argument("--output", default="calibration_results.json",
                        help="Output file for results")
    args = parser.parse_args()
    
    if args.env:
        envs_to_calibrate = [args.env]
    elif args.all:
        # Get all environments from registry or filesystem
        registry_path = ROOT / "envs" / "registry.yaml"
        if registry_path.exists():
            import yaml
            with registry_path.open() as f:
                registry = yaml.safe_load(f)
            envs_to_calibrate = list(registry.get("environments", {}).keys())
        else:
            envs_to_calibrate = [
                "glyph", "batchnorm_ema", "moco", "rope",
                "regex_state_machine", "sql_fixed_point"
            ]
    else:
        parser.error("Specify --env or --all")
    
    all_results = {}
    for env in envs_to_calibrate:
        print(f"Calibrating {env}...")
        try:
            results = calibrate_environment(env, args.seeds)
            all_results[env] = results
            print(f"  Done: {len(results['results'])} runs")
        except Exception as e:
            print(f"  Error: {e}")
            all_results[env] = {"error": str(e)}
    
    # Save results
    output_path = ROOT / args.output
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nCalibration results saved to {output_path}")
    print("\nNote: Full calibration with judge scoring requires Docker.")
    print("This script currently only verifies environment generation.")


if __name__ == "__main__":
    main()
