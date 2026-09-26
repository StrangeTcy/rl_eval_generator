"""Offline regressions for exact patch submission and failure attribution."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_runner
from arena.artifacts import _diff_directories
from arena.docker_backend import ContainerResult, DockerBackend, DockerBackendError
from arena.episode import SYSTEM_PROMPT


def _state(tmp_path: Path) -> dict:
    original = tmp_path / "original"
    workspace = tmp_path / "workspace"
    original.mkdir()
    workspace.mkdir()
    return {
        "episode_dir": str(tmp_path),
        "env_dir": str(tmp_path / "generated"),
        "original_workspace": str(original),
        "workspace": str(workspace),
        "patchable_files": ["model.py"],
        "required_files": [],
        "sandbox": "local",
        "seed": 0,
    }


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"alpha\n", b"alpha"),
        (b"alpha", b"alpha\n"),
        (b"alpha\n", b"beta"),
        (b"alpha\r\n", b"alpha\n"),
    ],
)
def test_submission_patch_preserves_exact_newline_edits(tmp_path, before, after):
    state = _state(tmp_path)
    original = Path(state["original_workspace"])
    workspace = Path(state["workspace"])
    (original / "model.py").write_bytes(before)
    (workspace / "model.py").write_bytes(after)

    patch, changed = env_runner._make_submission_patch(state)
    assert changed == ["model.py"]
    assert patch.read_bytes().startswith(b"--- a/model.py\n+++ b/model.py\n@@")
    assert _diff_directories(original, workspace)
    if before.rstrip(b"\r\n") == after.rstrip(b"\r\n") and b"\r" not in before + after:
        assert b"\\ No newline at end of file" in patch.read_bytes()

    applied = tmp_path / "applied"
    applied.mkdir()
    (applied / "model.py").write_bytes(before)
    process = subprocess.run(
        ["patch", "--batch", "-p1", "-d", str(applied), "-i", str(patch)],
        capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert (applied / "model.py").read_bytes() == after


def test_show_diff_handles_created_and_deleted_files(tmp_path):
    state = _state(tmp_path)
    (Path(state["original_workspace"]) / "deleted.py").write_text("old\n")
    (Path(state["workspace"]) / "added.py").write_text("new\n")

    text, info = env_runner._show_diff(state)
    assert info["changed_files"] == ["added.py", "deleted.py"]
    assert "after/added.py" in text and "+new" in text
    assert "before/deleted.py" in text and "-old" in text


def test_symlinked_workspace_cannot_leak_host_files_through_diffs_or_submission(tmp_path):
    state = _state(tmp_path)
    original = Path(state["original_workspace"])
    workspace = Path(state["workspace"])
    (original / "model.py").write_text("original\n")
    secret = tmp_path / "host_secret.py"
    secret.write_text("HOST_ONLY_SECRET_CANARY\n")
    (workspace / "model.py").symlink_to(secret)

    changed = env_runner._changed_files(state)
    text, _ = env_runner._show_diff(state)
    artifact = _diff_directories(original, workspace)
    assert changed == ["model.py"]
    assert "symlink contents omitted" in text + artifact
    assert "HOST_ONLY_SECRET_CANARY" not in text + artifact
    assert "HOST_ONLY_SECRET_CANARY" not in env_runner._search(
        state, {"pattern": "HOST_ONLY_SECRET_CANARY", "path": "."}
    )[0]
    with pytest.raises(ValueError, match="symlink"):
        env_runner._make_submission_patch(state)
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 0
    assert info["judge_result"]["failure_mode"] == "patch_invalid"
    assert "HOST_ONLY_SECRET_CANARY" not in json.dumps(info)


def test_parent_directory_symlink_cannot_leak_file_from_nested_original(tmp_path):
    state = _state(tmp_path)
    original = Path(state["original_workspace"])
    workspace = Path(state["workspace"])
    (original / "src").mkdir()
    (original / "src" / "model.py").write_text("original\n")
    secret_dir = tmp_path / "host_dir"
    secret_dir.mkdir()
    (secret_dir / "model.py").write_text("HOST_ONLY_SECRET_CANARY\n")
    (workspace / "src").symlink_to(secret_dir, target_is_directory=True)
    state["patchable_files"] = ["src/model.py"]

    assert "src/model.py" in env_runner._changed_files(state)
    text, _ = env_runner._show_diff(state)
    assert "HOST_ONLY_SECRET_CANARY" not in text + _diff_directories(original, workspace)
    with pytest.raises(ValueError, match="symlink"):
        env_runner._make_submission_patch(state)


def test_large_and_binary_agent_files_are_not_inlined_or_loaded_as_patches(tmp_path):
    state = _state(tmp_path)
    original = Path(state["original_workspace"])
    workspace = Path(state["workspace"])
    (original / "model.py").write_text("original\n")
    with (workspace / "model.py").open("wb") as handle:
        handle.truncate(env_runner.MAX_SUBMISSION_SOURCE_BYTES + 1)
    (workspace / "checkpoint.pt").write_bytes(b"\0BINARY\0" * 200)

    changed = env_runner._changed_files(state)
    text, _ = env_runner._show_diff(state)
    artifact = _diff_directories(original, workspace)
    assert changed == ["checkpoint.pt", "model.py"]
    assert "large file contents omitted" in text + artifact
    assert "binary file contents omitted" in text + artifact
    assert "BINARY" not in text + artifact
    assert len(text + artifact) < 1500
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 0
    assert info["judge_result"]["failure_mode"] == "patch_invalid"
    assert "too large" in info["judge_result"]["notes"][0]


def test_same_size_binary_edits_still_appear_in_artifact_diff(tmp_path):
    state = _state(tmp_path)
    original = Path(state["original_workspace"])
    workspace = Path(state["workspace"])
    (original / "checkpoint.pt").write_bytes(b"\0before")
    (workspace / "checkpoint.pt").write_bytes(b"\0after!")
    assert env_runner._changed_files(state) == ["checkpoint.pt"]
    diff = _diff_directories(original, workspace)
    assert "checkpoint.pt" in diff and "[changed contents omitted]" in diff
    assert "\0before" not in diff and "\0after!" not in diff


def test_deleted_patchable_source_is_rejected_instead_of_recreated_empty(tmp_path):
    state = _state(tmp_path)
    (Path(state["original_workspace"]) / "model.py").write_text("code\n")
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 0
    assert info["judge_result"]["failure_mode"] == "patch_invalid"
    assert "deleted" in info["judge_result"]["notes"][0]


@pytest.mark.parametrize(
    ("stdout", "returncode", "mode"),
    [
        ('{"verdict":"PASS","score":1,"failure_mode":"pass"}', 0, "pass"),
        ('{"verdict":"FAIL","score":0,"failure_mode":"patch_invalid"}', 1, "patch_invalid"),
        ('{"verdict":"PASS","score":1,"failure_mode":"pass"}', 137, "judge_runtime_error"),
        ('{"verdict":"PASS","score":0,"failure_mode":"pass"}', 0, "judge_runtime_error"),
        ('{"score":1}', 0, "judge_runtime_error"),
        ('{"verdict":"FAIL","score":0,"failure_mode":"unknown"}', 1, "judge_runtime_error"),
        ('{"verdict":"PASS","score":1,"failure_mode":"unknown"}', 0, "judge_runtime_error"),
        ('{"verdict":"PASS","score":NaN,"failure_mode":"pass"}', 0, "judge_runtime_error"),
        ("a judge traceback", 1, "judge_runtime_error"),
    ],
)
def test_only_complete_consistent_judge_results_are_scored(stdout, returncode, mode):
    assert env_runner._judge_result(stdout, "judge stderr", returncode)["failure_mode"] == mode


@pytest.mark.parametrize("doc_line", ["++ train.py", "++ outside.py"])
def test_judge_patch_parser_ignores_source_lines_that_look_like_file_headers(
    tmp_path, monkeypatch, doc_line
):
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id="offline_patch_headers", env="batchnorm_ema",
        difficulty="easy,easy,easy,easy,easy", seed=0, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    model = Path(state["workspace"]) / "model.py"
    original = model.read_text(encoding="utf-8")
    header = '"""ResNet-style model with BatchNorm for CIFAR classification."""'
    assert header in original
    model.write_text(original.replace(header, f'"""Description.\n{doc_line}\n"""', 1))
    patch, changed = env_runner._make_submission_patch(state)
    assert changed == ["model.py"]
    assert "+" + doc_line in patch.read_text(encoding="utf-8")

    # The judge_lib template can import an empty torch shim here: this test
    # exercises only patch validation and the required-file policy, not ML.
    judge_dir = Path(state["env_dir"]) / "judge"
    (judge_dir / "torch.py").write_text("# offline patch parser test\n")
    env = {**os.environ, "PYTHONPATH": str(judge_dir),
           "JUDGE_PATCH_PATH": str(patch), "JUDGE_ORIGINALS_DIR": state["original_workspace"]}
    script = (
        "import shutil, patch_validator, judge_lib\n"
        "patched = patch_validator.validate_patch()\n"
        "result = judge_lib.base_result()\n"
        "assert judge_lib.changed_files_from_patch() == {'model.py'}\n"
        "assert not judge_lib.require_changed_files(result, {'model.py', 'train.py'})\n"
        "shutil.rmtree(patched)\n"
    )
    process = subprocess.run(
        [sys.executable, "-c", script], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr + process.stdout


def test_patch_validator_rejects_no_op_hunks_as_required_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id="offline_noop_patch", env="batchnorm_ema",
        difficulty="easy,easy,easy,easy,easy", seed=0, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    first = (Path(state["original_workspace"]) / "model.py").read_text().splitlines()[0]
    patch = Path(state["episode_dir"]) / "submission.patch"
    patch.write_text(f"--- a/model.py\n+++ b/model.py\n@@ -1 +1 @@\n-{first}\n+{first}\n")
    env = {**os.environ, "PYTHONPATH": str(Path(state["env_dir"]) / "judge"),
           "JUDGE_PATCH_PATH": str(patch), "JUDGE_ORIGINALS_DIR": state["original_workspace"]}
    process = subprocess.run(
        [sys.executable, str(Path(state["env_dir"]) / "judge/patch_validator.py")],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert process.returncode == 1
    assert "no effective change" in process.stdout


def test_model_cannot_shorten_local_judge_timeout(tmp_path, monkeypatch):
    state = _state(tmp_path)
    state["patchable_files"] = []
    monkeypatch.setenv("JUDGE_SUBMIT_TIMEOUT", "123")
    seen_timeouts = []

    def judge_stub(command, **kwargs):
        seen_timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(
            command, 1, stdout='{"verdict":"FAIL","score":0,"failure_mode":"patch_invalid"}',
            stderr="",
        )

    monkeypatch.setattr(env_runner.subprocess, "run", judge_stub)
    env_runner._submit(state, {"confirm": True, "timeout": 1})
    env_runner._submit(state, {"confirm": True, "timeout": "not an integer"}, judge_timeout=77)
    assert seen_timeouts == [123, 77]  # trusted CLI timeout, never model-supplied


def test_local_judge_timeout_is_not_not_submitted(tmp_path, monkeypatch):
    state = _state(tmp_path)
    state["patchable_files"] = []

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("judge.py", 1)

    monkeypatch.setattr(env_runner.subprocess, "run", timed_out)
    _observation, score, done, info = env_runner._submit(state, {"confirm": True, "timeout": 1})
    assert done and score == 0
    assert info["judge_result"]["failure_mode"] == "judge_runtime_error"
    assert "timed out" in info["judge_result"]["notes"][0]


def test_controller_submit_tool_explains_action_instead_of_permission_error(tmp_path, monkeypatch, capsys):
    assert 'Do not run that tool or exit to submit' in SYSTEM_PROMPT
    assert '{"type": "submit", "confirm": true}' in SYSTEM_PROMPT
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id="offline_submit_tool", env="regex_state_machine",
        difficulty="easy,easy", seed=0, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    tool = Path(state["tools"]) / "submit.py"
    spec = importlib.util.spec_from_file_location("generated_submit_tool", tool)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os.path, "isdir", lambda path: path != "/submission")
    with pytest.raises(SystemExit) as raised:
        module.main()
    assert raised.value.code == 2
    message = capsys.readouterr().err
    assert '{"type":"submit","confirm":true}' in message
    assert "interactive run_eval.sh only" in message


def test_docker_command_failure_is_distinct_from_agent_shell_exit_125(tmp_path, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise DockerBackendError("Docker command timed out")

    backend = DockerBackend(command_runner=timeout)
    result = backend.run_agent("agent-image", tmp_path, tmp_path, "echo hello")
    assert result.returncode == 125 and result.backend_error is True

    def shell_failure(command, **_kwargs):
        return subprocess.CompletedProcess(command, 125, stdout="", stderr="agent chose exit 125")

    backend = DockerBackend(command_runner=shell_failure)
    result = backend.run_agent("agent-image", tmp_path, tmp_path, "exit 125")
    assert result.returncode == 125 and result.backend_error is False

    def docker_failure(command, **_kwargs):
        return subprocess.CompletedProcess(command, 125, stdout="", stderr="docker: daemon unavailable")

    backend = DockerBackend(command_runner=docker_failure)
    result = backend.run_agent("agent-image", tmp_path, tmp_path, "echo hello")
    assert result.backend_error is True

    class OfflineDocker:
        def run_agent(self, *_args):
            return ContainerResult("", "Docker command timed out", 125, ["docker", "run"], True)

    monkeypatch.setattr(env_runner, "DockerBackend", lambda: OfflineDocker())
    state = {"sandbox": "docker", "agent_image": {"name": "agent-image"},
             "workspace": str(tmp_path), "tools": str(tmp_path)}
    _observation, info = env_runner._run_shell(state, "ls")
    assert info["infrastructure_failure"] == "agent_container_error"


def test_runner_stops_on_agent_sandbox_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path)
    episode = tmp_path / "offline_sandbox"
    episode.mkdir()
    state = {"episode_id": "offline_sandbox", "episode_dir": str(episode), "done": False,
             "max_steps": 3, "step": 0, "history": []}
    env_runner._save_state(state)
    monkeypatch.setattr(
        env_runner, "_run_shell", lambda *_args: (
            "Docker command timed out", {"infrastructure_failure": "agent_container_error"}
        ),
    )
    env_runner.step(SimpleNamespace(episode="offline_sandbox", action='{"cmd":"ls"}'))
    response = json.loads(capsys.readouterr().out)
    assert response["done"] is True
    assert response["info"]["infrastructure_failure"] == "agent_container_error"


def test_runner_submit_exception_is_terminal_controller_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path)
    episode = tmp_path / "offline_case"
    episode.mkdir()
    state = {"episode_id": "offline_case", "episode_dir": str(episode), "done": False,
             "max_steps": 2, "step": 0, "history": []}
    env_runner._save_state(state)

    def fail_submit(_state, _action):
        raise OSError("judge runner disk error")

    monkeypatch.setattr(env_runner, "_submit", fail_submit)
    env_runner.step(SimpleNamespace(episode="offline_case", action='{"type":"submit","confirm":true}'))
    response = json.loads(capsys.readouterr().out)
    assert response["done"] is True
    assert response["info"]["judge_result"]["failure_mode"] == "controller_error"
    assert response["reward"] == 0
