from pathlib import Path
import json
import os
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


def test_rope_tools_write_standard_event_log():
    name = "smoke_rope_events"
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
    run("generate_env.py", "--env", "rope", "--name", name, "--difficulty", "hard,hard,hard,hard,hard,hard,hard", "--seed", "1")
    workspace = ROOT / name / "agent" / "workspace"
    tools = ROOT / name / "agent" / "tools"
    env = {"WORKSPACE": str(workspace)}
    subprocess.run([sys.executable, str(tools / "extract_pdf.py"), str(workspace / "paper_excerpt.pdf"), "--out", str(workspace / "paper_excerpt.md"), "--attempt", "1"], check=True, env=env, capture_output=True, text=True)
    subprocess.run([sys.executable, str(tools / "read_paper.py"), "index"], check=True, env=env, capture_output=True, text=True)
    subprocess.run([sys.executable, str(tools / "inspect_logs.py")], check=True, env=env, capture_output=True, text=True)
    event_log = workspace / "logs" / "events.jsonl"
    assert event_log.exists()
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert [event["tool"] for event in events[:2]] == ["extract_pdf", "read_paper"]
    assert events[0]["status"] in {"ok", "warning"}
    subprocess.run(["rm", "-rf", name], cwd=ROOT)


def test_every_env_ships_logging_tools():
    expected = {"tool_state.py", "run_train.py", "run_eval.py", "inspect_logs.py"}
    cases = [
        ("glyph", "easy,easy,easy,easy,easy"),
        ("batchnorm_ema", "easy,easy,easy,easy"),
        ("moco", "easy,easy,easy,easy,easy"),
        ("rope", "hard,hard,hard,hard,hard,hard,hard"),
    ]
    for env, diff in cases:
        name = f"smoke_logtools_{env}"
        subprocess.run(["rm", "-rf", name], cwd=ROOT)
        run("generate_env.py", "--env", env, "--name", name, "--difficulty", diff, "--seed", "1")
        tools = {p.name for p in (ROOT / name / "agent" / "tools").iterdir()}
        assert expected <= tools, f"{env} missing logging tools: {expected - tools}"
        subprocess.run(["rm", "-rf", name], cwd=ROOT)


def test_generic_env_records_and_inspects_events():
    # inspect_logs.py is torch-free, so this exercises the shared logging path
    # without requiring a training run.
    name = "smoke_generic_events"
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
    run("generate_env.py", "--env", "glyph", "--name", name, "--difficulty", "easy,easy,easy,easy,easy", "--seed", "1")
    workspace = ROOT / name / "agent" / "workspace"
    tools = ROOT / name / "agent" / "tools"
    env = {"WORKSPACE": str(workspace), "PATH": os.environ.get("PATH", "")}
    subprocess.run([sys.executable, str(tools / "inspect_logs.py")], check=True, env=env, capture_output=True, text=True)
    event_log = workspace / "logs" / "events.jsonl"
    assert event_log.exists()
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert any(e["tool"] == "inspect_logs" for e in events)
    subprocess.run(["rm", "-rf", name], cwd=ROOT)
