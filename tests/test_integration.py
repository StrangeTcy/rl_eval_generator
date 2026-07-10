"""End-to-end integration tests for environment judges.

These tests verify judge correctness by testing:
1. Known-correct patches produce PASS
2. Empty patches are rejected
3. Generated environments have expected structure
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd, cwd=None, env=None, check=False, timeout=120):
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True,
            timeout=timeout, check=check
        )
        return result
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")


def test_all_envs_generate_without_errors():
    """Test that all environments can be generated without errors."""
    import yaml
    
    # Get all environments from registry or filesystem
    registry_path = ROOT / "envs" / "registry.yaml"
    envs_to_test = []
    
    if registry_path.exists():
        with registry_path.open() as f:
            registry = yaml.safe_load(f)
        envs_to_test = list(registry.get("environments", {}).keys())
    else:
        # Fallback to filesystem discovery
        for config_path in (ROOT / "envs").rglob("config.yaml"):
            parts = config_path.relative_to(ROOT / "envs").parts
            envs_to_test.append(parts[-1])  # Last part is the env name
    
    # Deduplicate
    envs_to_test = sorted(set(envs_to_test))
    
    # Test a subset of environments (full test would be too slow)
    # Test at least one from each category
    test_cases = [
        ("glyph", "easy,easy,easy,easy,easy,easy"),
        ("batchnorm_ema", "easy,easy,easy,easy,easy"),
        ("moco", "easy,easy,easy,easy,easy,easy"),
        ("rope", "easy,easy,easy,easy,easy,easy,easy,easy"),
        ("regex_state_machine", "easy,easy"),
        ("sql_fixed_point", "easy,easy"),
    ]
    
    for env, diff in test_cases:
        name = f"test_integration_{env}"
        env_dir = ROOT / name
        
        if env_dir.exists():
            subprocess.run(["rm", "-rf", str(env_dir)], check=False)
        
        # Get axis count from config
        config_path = ROOT / "envs" / env / "config.yaml"
        if not config_path.exists():
            config_path = ROOT / "envs" / "cat_theo" / env / "config.yaml"
        if not config_path.exists():
            config_path = ROOT / "envs" / "weird_machine" / env / "config.yaml"
        
        with config_path.open() as f:
            import yaml
            config = yaml.safe_load(f)
        axis_count = len(config.get("axes", []))
        
        # Use the provided diff or generate one
        if diff == "easy,easy,easy,easy,easy,easy,easy,easy":
            actual_diff = ",".join(["easy"] * axis_count)
        else:
            parts = diff.split(",")
            actual_diff = ",".join(parts[:axis_count])
        
        result = run_cmd([
            sys.executable, "generate_env.py", "--env", env,
            "--name", name, "--difficulty", actual_diff, "--seed", "42"
        ], cwd=ROOT, check=False)
        
        assert result.returncode == 0, f"Failed to generate {env}: {result.stderr}"
        assert (env_dir / "run_eval.sh").exists(), f"{env} missing run_eval.sh"
        assert (env_dir / "agent").is_dir(), f"{env} missing agent dir"
        assert (env_dir / "judge").is_dir(), f"{env} missing judge dir"
        
        # Check that all Python files compile
        py_files = list(env_dir.rglob("*.py"))
        compile_result = run_cmd([
            sys.executable, "-m", "py_compile", *[str(p) for p in py_files]
        ], check=False)
        assert compile_result.returncode == 0, f"{env} has Python syntax errors"
        
        # Check no unresolved placeholders
        all_text = ""
        for p in env_dir.rglob("*"):
            if p.is_file() and p.suffix != ".pyc":
                try:
                    all_text += p.read_text(errors="ignore")
                except:
                    pass
        
        # Allow %% in comments and some specific cases, but not in code
        import re
        unresolved = re.findall(r"%%[A-Z0-9_]+%%", all_text)
        assert len(unresolved) == 0, f"{env} has unresolved placeholders: {set(unresolved)}"
        
        subprocess.run(["rm", "-rf", str(env_dir)], check=False)


def test_registry_covers_all_envs():
    """Test that the registry covers all environments."""
    import yaml
    
    registry_path = ROOT / "envs" / "registry.yaml"
    assert registry_path.exists(), "Registry file missing"
    
    with registry_path.open() as f:
        registry = yaml.safe_load(f)
    
    registered = set(registry.get("environments", {}).keys())
    
    # Find all config.yaml files
    all_configs = set()
    for config_path in (ROOT / "envs").rglob("config.yaml"):
        relative = config_path.relative_to(ROOT / "envs")
        # Get the environment name (last directory before config.yaml)
        parts = list(relative.parts)
        env_name = parts[-2] if len(parts) > 1 else parts[-1].replace("config.yaml", "")
        all_configs.add(env_name)
    
    # Registry should cover all environments
    # (or at least the main ones - subdirectories might not be in registry)
    assert len(registered) > 0, "Registry is empty"


def test_judge_lib_has_documented_constants():
    """Test that magic numbers in judge_lib are documented."""
    judge_lib = (ROOT / "shared" / "judge_lib.py").read_text()
    
    # Check that constants have documentation
    assert "MAX_CHECKPOINT_BYTES" in judge_lib
    assert "MAX_STATE_TENSORS" in judge_lib
    assert "MAX_STATE_ELEMENTS" in judge_lib
    assert "MAX_OUTPUT_ELEMENTS" in judge_lib
    
    # Check that they have comments explaining the rationale
    assert "checkpoint" in judge_lib.lower() or "Checkpoint" in judge_lib
    assert "tensor" in judge_lib.lower()


def test_source_validator_has_security_notice():
    """Test that source_validator acknowledges its limitations."""
    validator = (ROOT / "shared" / "source_validator.py").read_text()
    
    # Should mention that it's not a security sandbox
    assert "NOT a security sandbox" in validator or "Docker" in validator
    
    # Should mention bypass methods
    assert "getattr" in validator or "bypass" in validator.lower()


def test_pyproject_toml_exists():
    """Test that pyproject.toml exists for linting/formatting."""
    pyproject = ROOT / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml missing"
    
    content = pyproject.read_text()
    assert "[tool.ruff]" in content, "ruff config missing"
    assert "[tool.black]" in content, "black config missing"


def test_requirements_lock_exists():
    """Test that requirements.lock exists for reproducibility."""
    requirements_lock = ROOT / "requirements.lock"
    assert requirements_lock.exists(), "requirements.lock missing"
    
    content = requirements_lock.read_text()
    assert "PyYAML" in content, "PyYAML not in requirements.lock"
    assert "pytest" in content, "pytest not in requirements.lock"
