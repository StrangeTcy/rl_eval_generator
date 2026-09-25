#!/usr/bin/env python3
"""Validate suite reference behavior without making provider/API calls.

This static gate generates one representative case per manifest environment,
compiles the generated Python, checks judge globals and deferred scripts, and
optionally checks that a known-good patch applies. Configured reference
self-tests are executed separately. No provider module, credential, or network
operation is used here.

A patch applying, or a judge compiling, does NOT establish that it grades a
correct submission correctly. ``model_sweep_allowed`` is the legacy static
readiness field; live schedulers additionally require behavioral reference
coverage or an explicit operator override before any provider calls.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.judge_preflight import validate_generated_judge  # noqa: E402
from tools.suite_inventory import _load_yaml, build_manifest  # noqa: E402

# Additional environments can declare a path under
# ``oracle.known_good_patch`` in their own config.yaml.  Do not infer that an
# example patch is current merely because it exists; a declared patch must
# apply cleanly to the pinned generated case.


def _representative_difficulty(config: dict[str, Any], oracle: dict[str, Any]) -> str:
    configured = oracle.get("difficulty")
    if isinstance(configured, str) and configured.strip():
        return configured
    values: list[str] = []
    for axis in config.get("axes", []):
        levels = axis.get("levels", {}) if isinstance(axis, dict) else {}
        names = list(levels) if isinstance(levels, dict) else []
        if not names:
            raise ValueError("oracle case cannot select a difficulty from an empty axis")
        values.append("hard" if "hard" in names else names[0])
    return ",".join(values)


def _run(command: list[str], *, cwd: Path, timeout: float = 180) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"timed out after {timeout:g}s: {exc}"
    return result.returncode, (result.stdout + result.stderr)[-5000:]


def _compile_generated(output: Path) -> tuple[bool, str]:
    python_files = [str(path) for path in output.rglob("*.py")]
    if not python_files:
        return False, "generated case contains no Python files"
    code, detail = _run([sys.executable, "-m", "py_compile", *python_files], cwd=output)
    if code != 0:
        return False, detail
    try:
        validate_generated_judge(output / "judge" / "judge.py")
    except (OSError, ValueError, SyntaxError) as exc:
        return False, f"judge template check failed: {exc}"
    return True, detail


def _apply_known_good_patch(output: Path, patch_path: Path) -> tuple[bool, str]:
    workspace = output / "agent" / "workspace"
    if not workspace.is_dir():
        return False, "generated case has no agent/workspace directory"
    patch_file = output / ".oracle.patch"
    shutil.copyfile(patch_path, patch_file)
    code, detail = _run(
        ["patch", "--dry-run", "-p1", "-i", str(patch_file)],
        cwd=workspace,
        timeout=30,
    )
    return code == 0, detail


def _configured_self_test(root: Path, environment: str, oracle: dict[str, Any]) -> tuple[bool | None, str | None]:
    kind = str(oracle.get("reference_behavior", "")).strip().lower()
    if kind == "public_bayes_oracle" or environment == "epistemic_games":
        code, detail = _run(
            [sys.executable, str(root / "tools" / "public_bayes_oracle.py"), "--self-test"],
            cwd=root,
            timeout=60,
        )
        return code == 0, detail
    # Compilation is not a behavioral self-test. Do not label it "passed".
    return None, None


def validate_manifest_oracles(
    manifest: dict[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return a zero-call oracle report for the environments in ``manifest``."""

    root = root.resolve()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for environment in manifest.get("environments", []):
        if not isinstance(environment, dict):
            continue
        name = str(environment.get("environment", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        config_path = root / str(environment.get("config_path", ""))
        result: dict[str, Any] = {
            "environment": name,
            "config_path": str(config_path.relative_to(root)) if config_path.is_file() else None,
            "status": "failed",
            "api_calls": 0,
            "provider_calls": 0,
            "reference_behavior": "judge_reference_compile",
        }
        try:
            config = _load_yaml(config_path)
            oracle = config.get("oracle", {})
            if not isinstance(oracle, dict):
                raise ValueError("oracle must be a mapping when configured")
            difficulty = _representative_difficulty(config, oracle)
            temp_root = Path(tempfile.mkdtemp(prefix="oracle-preflight-", dir=root))
            output_name = temp_root.name + "-generated"
            output = root / output_name
            generated_name = output_name
            code, detail = _run(
                [
                    sys.executable,
                    str(root / "generate_env.py"),
                    "--env",
                    name,
                    "--name",
                    generated_name,
                    "--difficulty",
                    difficulty,
                    "--seed",
                    str(int(oracle.get("seed", 0))),
                ],
                cwd=root,
                timeout=180,
            )
            if code != 0:
                raise RuntimeError(f"generation failed: {detail}")
            compiled, compile_detail = _compile_generated(output)
            if not compiled:
                raise RuntimeError(f"generated Python did not compile: {compile_detail}")
            result.update({"difficulty": difficulty, "generated": True, "judge_compiled": True})

            patch_value = oracle.get("known_good_patch")
            if patch_value:
                patch_path = root / str(patch_value)
                if not patch_path.is_file():
                    raise FileNotFoundError(f"known-good patch not found: {patch_value}")
                applied, patch_detail = _apply_known_good_patch(output, patch_path)
                result["known_good_patch"] = str(patch_path.relative_to(root))
                result["known_good_patch_applies"] = applied
                if not applied:
                    raise RuntimeError(f"known-good patch did not apply: {patch_detail}")
                result["reference_behavior"] = "known_good_patch"

            reference_kind = str(oracle.get("reference_behavior", "")).strip().lower()
            if reference_kind == "public_bayes_oracle" or name == "epistemic_games":
                result["reference_behavior"] = "public_bayes_oracle"
            reference_ok, reference_detail = _configured_self_test(root, name, oracle)
            result["reference_self_test"] = (
                "not_configured" if reference_ok is None else "passed" if reference_ok else "failed"
            )
            # A patch merely *applying* is not proof its judge would pass it.
            result["behavioral_reference_executed"] = reference_ok is not None
            if reference_detail:
                result["reference_detail"] = reference_detail
            if reference_ok is False:
                raise RuntimeError("configured reference self-test failed")
            result["status"] = "ready"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            result["error"] = str(exc)[-5000:]
        finally:
            if "output" in locals():
                shutil.rmtree(output, ignore_errors=True)
                del output
            if "temp_root" in locals():
                shutil.rmtree(temp_root, ignore_errors=True)
                del temp_root
        results.append(result)

    failures = [result for result in results if result.get("status") != "ready"]
    unverified = [
        result["environment"] for result in results
        if not result.get("behavioral_reference_executed", False)
    ]
    return {
        "schema_version": 1,
        "event": "zero_api_oracle_preflight",
        "api_calls": 0,
        "provider_calls": 0,
        # Legacy readiness reports that the static checks completed, not that
        # the judge has passed a known-good submission on every selected case.
        "model_sweep_allowed": not failures,
        "behavioral_coverage_complete": bool(results) and not unverified,
        "unverified_environments": unverified,
        "results": results,
        "failure_count": len(failures),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=Path("runs/oracle_preflight.json"))
    args = parser.parse_args(argv)
    try:
        manifest = (
            json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.manifest
            else build_manifest(root=args.root, matrix="representative", seeds=[0])
        )
        report = validate_manifest_oracles(manifest, root=args.root)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"oracle preflight failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["model_sweep_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
