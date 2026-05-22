from pathlib import Path
import subprocess
import sys
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(*args, check=True):
    return subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True, check=check)


def test_configs_parse():
    for path in (ROOT / "envs").glob("*/config.yaml"):
        yaml.safe_load(path.read_text())


def test_path_traversal_rejected():
    proc = run("generate_env.py", "--env", "glyph", "--name", "../escape", "--difficulty", "easy,easy,easy,easy,easy", check=False)
    assert proc.returncode != 0
    assert "escapes" in (proc.stdout + proc.stderr)


def test_unknown_placeholder_rejected(tmp_path):
    env = ROOT / "envs" / "glyph" / "files" / "prompt.md"
    original = env.read_text()
    try:
        env.write_text(original + "\n%%DOES_NOT_EXIST%%\n")
        proc = run("generate_env.py", "--env", "glyph", "--name", "tmp_bad", "--difficulty", "easy,easy,easy,easy,easy", check=False)
        assert proc.returncode != 0
        assert "Unresolved" in (proc.stdout + proc.stderr)
    finally:
        env.write_text(original)
        subprocess.run(["rm", "-rf", "tmp_bad"], cwd=ROOT)


def test_smoke_generate_all_envs():
    cases = [
        ("glyph", "smoke_glyph", "easy,easy,easy,easy,easy"),
        ("batchnorm_ema", "smoke_bn", "easy,easy,easy,easy"),
        ("moco", "smoke_moco", "easy,easy,easy,easy,easy"),
        ("rope", "smoke_rope", "easy,easy,easy,easy,easy,easy,easy"),
    ]
    for env, name, diff in cases:
        subprocess.run(["rm", "-rf", name], cwd=ROOT)
        run("generate_env.py", "--env", env, "--name", name, "--difficulty", diff, "--seed", "1")
        generated = ROOT / name
        assert generated.exists()
        contents = "\n".join(p.read_text(errors="ignore") for p in generated.rglob("*") if p.is_file())
        assert not re.search(r"%%[A-Z0-9_]+%%", contents)
        py_files = [str(p) for p in generated.rglob("*.py")]
        subprocess.run([sys.executable, "-m", "py_compile", *py_files], check=True)
        subprocess.run(["rm", "-rf", name], cwd=ROOT)


def test_patch_validator_rejects_non_patchable_paths():
    name = "smoke_patch_paths"
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
    run("generate_env.py", "--env", "glyph", "--name", name, "--difficulty", "easy,easy,easy,easy,easy")
    import importlib.util
    validator_path = ROOT / name / "judge" / "patch_validator.py"
    spec = importlib.util.spec_from_file_location("generated_patch_validator", validator_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    bad_patch = "--- a/model.py\n+++ b/sitecustomize.py\n@@ -1 +1 @@\n-x\n+y\n"
    try:
        module.validate_patch_paths(bad_patch)
    except RuntimeError as exc:
        assert "non-patchable" in str(exc)
    else:
        raise AssertionError("malicious patch path was accepted")
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
