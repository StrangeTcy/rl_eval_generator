#!/usr/bin/env python3
"""Run the real local production judges for the eight scored structural tasks.

This is an offline infrastructure gate.  It never contacts a model provider.
The valid candidate embeds the reviewed public network algorithm so the judge
can be exercised with a known-good certificate producer; the other variants
exercise the production parser, source validator, independent verifier, and
scoring failure paths.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.metadata as metadata
import io
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402

ENVIRONMENTS = (
    "recursive_gluing",
    "recursive_gluing_discovery",
    "recursive_maze_gluing",
    "recursive_distributed_gluing",
    "recursive_epistemic_gluing",
    "recursive_compiler_bootstrap",
    "recursive_error_correcting_codes",
    "recursive_coarse_graining",
)

DIFFICULTY = {
    "recursive_gluing": "easy,easy,easy,easy",
    "recursive_gluing_discovery": "easy,easy,easy,easy,easy",
    "recursive_maze_gluing": "easy,easy,easy,easy",
    "recursive_distributed_gluing": "easy,easy,easy",
    "recursive_epistemic_gluing": "easy,easy,easy,easy",
    "recursive_compiler_bootstrap": "easy,easy,easy",
    "recursive_error_correcting_codes": "easy,easy,easy",
    "recursive_coarse_graining": "easy,easy,easy",
}
SEED = 41


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def class_name(source: str) -> str:
    tree = ast.parse(source)
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError(f"expected one generated solver class, found {classes}")
    return classes[0]


def candidate_source(environment: str, original: str, variant: str) -> str:
    model = class_name(original)
    if variant == "malformed":
        return f"class {model}(\n"
    if variant == "reference_accuracy_only":
        return (
            f"class {model}:\n"
            "    def solve(self, instance):\n"
            "        return {'reference_acc': 1.0}\n"
        )
    if variant == "incomplete":
        return (
            f"class {model}:\n"
            "    def solve(self, instance):\n"
            "        return {}\n"
        )
    if variant == "wrong":
        return (
            f"class {model}:\n"
            "    def solve(self, instance):\n"
            "        return {'status': 'unsat'}\n"
        )

    network_path = ROOT / "envs" / "cat_theo" / environment / "files" / "network.py"
    network = network_path.read_text(encoding="utf-8")
    # Candidate source is checked by the production allowlist.  These imports
    # are either unused by the reference entry point or replaced locally; the
    # network module itself remains byte-for-byte the reviewed algorithm.
    lines = []
    for line in network.splitlines():
        stripped = line.strip()
        if stripped.startswith("from __future__ import"):
            continue
        if stripped in {"import json", "import time", "from operator import index"}:
            continue
        lines.append(line)
    if environment == "recursive_compiler_bootstrap":
        lines.append("")
        lines.append("def index(value):")
        lines.append("    return int(value)")
    call = "reference_solve(instance)" if environment == "recursive_gluing" else "reference_certificate(instance)"
    lines.extend(
        [
            "",
            f"class {model}:",
            "    def solve(self, instance):",
            f"        return {call}",
        ]
    )
    return "\n".join(lines) + "\n"


def reset_episode(environment: str, episode_id: str, output: Path) -> dict:
    args = SimpleNamespace(
        episode_id=episode_id,
        env=environment,
        difficulty=DIFFICULTY[environment],
        seed=SEED,
        max_steps=1,
        sandbox="local",
        keep_images=False,
        keep_workspace=True,
        interventions="",
    )
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        env_runner.reset(args)
    state = env_runner._load_state(episode_id)
    state["reset_stdout"] = captured.getvalue()
    return state


def run_variant(environment: str, variant: str, output: Path) -> dict:
    episode_id = f"prod_{environment}_{variant}"
    state = reset_episode(environment, episode_id, output)
    workspace = Path(state["workspace"])
    solver_path = workspace / "solver.py"
    original = solver_path.read_text(encoding="utf-8")
    source = candidate_source(environment, original, variant)
    solver_path.write_text(source, encoding="utf-8")
    started = time.monotonic()
    observation, reward, done, info = env_runner._submit(
        state, {"confirm": True}, judge_timeout=1800
    )
    elapsed = round(time.monotonic() - started, 3)
    judge = info.get("judge_result") or {}
    episode_dir = Path(state["episode_dir"])
    record = {
        "environment": environment,
        "variant": variant,
        "episode_id": episode_id,
        "difficulty": DIFFICULTY[environment],
        "seed": SEED,
        "generation_id": state.get("provenance", {}).get("generation_id"),
        "pair_id": state.get("provenance", {}).get("pair_id"),
        "instance_sha256": env_runner._instance_hash(state),
        "solver_sha256": sha256_bytes(source.encode()),
        "reset_succeeded": True,
        "submission_done": bool(done),
        "runner_reward": reward,
        "judge_returncode": info.get("returncode"),
        "judge_result": judge,
        "judge_stdout": info.get("judge_stdout", ""),
        "judge_stderr": info.get("judge_stderr", ""),
        "elapsed_seconds": elapsed,
        "observation_tail": observation[-1000:],
        "stage_outcomes": judge.get("stage_outcomes", {}),
        "checks": judge.get("checks", {}),
        "metrics": judge.get("metrics", {}),
        "events": judge.get("events", []),
        "submission_patch_sha256": sha256_file(episode_dir / "submission.patch")
        if (episode_dir / "submission.patch").is_file()
        else None,
    }
    detail_dir = output / "per-environment" / environment
    detail_dir.mkdir(parents=True, exist_ok=True)
    (detail_dir / f"{variant}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def environment_record() -> dict:
    packages = {}
    for name in ("PyYAML", "pytest", "torch", "torchvision"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    import torch

    return {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "branch": subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
        "torch_version": torch.__version__,
        "torch_cuda_available": bool(torch.cuda.is_available()),
        "runner_os": "ubuntu-22.04",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    env_record = environment_record()
    source_paths = {}
    for environment in ENVIRONMENTS:
        for rel in ("config.yaml", "files/network.py", "files/judge.py", "files/solver.py"):
            path = ROOT / "envs" / "cat_theo" / environment / rel
            source_paths[str(path.relative_to(ROOT))] = sha256_file(path)
    env_record["source_hashes"] = source_paths
    (output / "environment.json").write_text(
        json.dumps(env_record, indent=2) + "\n", encoding="utf-8"
    )

    records = []
    variants = ("valid", "wrong", "incomplete", "malformed", "reference_accuracy_only")
    log_path = output / "production-judge.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "start", "environment": env_record}) + "\n")
        for environment in ENVIRONMENTS:
            for variant in variants:
                try:
                    record = run_variant(environment, variant, output)
                except Exception as exc:  # preserve infrastructure failures per case
                    record = {
                        "environment": environment,
                        "variant": variant,
                        "reset_succeeded": False,
                        "exception": type(exc).__name__ + ": " + str(exc),
                    }
                records.append(record)
                log.write(json.dumps(record, sort_keys=True) + "\n")
                log.flush()

    (output / "production-judge-results.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "commit": env_record["commit"],
                "branch": env_record["branch"],
                "frozen_seed": SEED,
                "frozen_difficulty": DIFFICULTY,
                "environments": list(ENVIRONMENTS),
                "variants": list(variants),
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    failures = []
    for record in records:
        result = record.get("judge_result") or {}
        verdict = result.get("verdict")
        if record.get("variant") == "valid" and verdict != "PASS":
            failures.append(record)
        if record.get("variant") != "valid" and verdict == "PASS":
            failures.append(record)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
