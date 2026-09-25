#!/usr/bin/env python3
"""Capability checks for constrained online notebooks.

A notebook is a controller/front-end, not automatically a sandbox.  This tool
reports whether the current runtime can safely run the repository's Docker-
backed episodes and distinguishes that from merely being able to inventory or
plan them.  It never contacts a model provider and never runs generated code.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _command_version(command: str, args: list[str]) -> dict[str, Any]:
    executable = shutil.which(command)
    if not executable:
        return {"available": False, "path": None, "version": None}
    try:
        process = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": True, "path": executable, "version": None}
    output = (process.stdout or process.stderr).strip().splitlines()
    return {"available": process.returncode == 0, "path": executable, "version": output[0] if output else None}


def _memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def detect_capabilities(root: Path = ROOT) -> dict[str, Any]:
    docker = _command_version("docker", ["version", "--format", "{{.Server.Version}}"])
    bwrap = _command_version("bwrap", ["--version"])
    patch = _command_version("patch", ["--version"])
    disk = shutil.disk_usage(root)
    has_gpu = False
    gpu_name = None
    if _module_available("torch"):
        try:
            import torch

            has_gpu = bool(torch.cuda.is_available())
            if has_gpu:
                gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            has_gpu = False
    isolated_executor = docker["available"]
    if not isolated_executor and bwrap["available"]:
        # Bubblewrap presence is useful information, but it is not treated as
        # equivalent to the repository's Docker policy automatically.
        isolated_executor = False
    dependencies = {
        "yaml": _module_available("yaml"),
        "pytest": _module_available("pytest"),
    }
    notebook = {
        "colab": bool(os.environ.get("COLAB_GPU") or os.environ.get("COLAB_RELEASE_TAG")),
        "kaggle": bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE") or os.environ.get("KAGGLE_URL_BASE")),
    }
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "root": str(root.resolve()),
        "notebook": notebook,
        "memory_bytes": _memory_bytes(),
        "disk_free_bytes": disk.free,
        "gpu": {"available": has_gpu, "name": gpu_name},
        "dependencies": dependencies,
        "commands": {"docker": docker, "bwrap": bwrap, "patch": patch},
        "execution": {
            "inventory": "ready" if dependencies["yaml"] else "missing_dependency",
            "docker_episode": "ready" if isolated_executor and patch["available"] else "requires_isolated_executor",
            "local_episode": "not_supported_by_default",
            "trajectory_direct_answer": "host_controller_only",
        },
        "warning": (
            "A notebook process is not a substitute for Docker isolation. "
            "Do not run generated code locally with provider credentials present."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    value = detect_capabilities(args.root)
    rendered = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
