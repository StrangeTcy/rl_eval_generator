"""Offline judge-oracle checks using real PyTorch when it is available.

Run with ``pip install torch`` in the host environment. CI's dependency-light
pytest invocation skips these; compile-only preflight is not a behavioral proof.
"""
from __future__ import annotations

import ast
import contextlib
import io
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_runner

ROOT = Path(__file__).resolve().parents[1]


def test_known_good_state_carry_patch_passes_real_judge(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id=f"oracle_statecarry_{uuid.uuid4().hex[:8]}",
        env="rd_state_carry",
        difficulty="easy,easy,easy,easy,easy",  # exactly the Atria pilot vector
        seed=0,
        max_steps=2,
        sandbox="local",
        keep_images=False,
        keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    implementation = Path(state["workspace"]) / "recurrent_block.py"
    source = implementation.read_text(encoding="utf-8")
    assert source.count("state = self.transition(x)") == 1
    implementation.write_text(
        source.replace("state = self.transition(x)", "state = self.transition(state)"),
        encoding="utf-8",
    )
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 1.0, info
    result = info["judge_result"]
    assert result["verdict"] == "PASS"
    assert result["checks"]["batch_independence"] is True
    assert result["passed_checks"] == result["total_checks"] == 5
    assert result["raw_accuracy"] == 1.0
    assert result["failure_mode"] == "pass"


def test_known_good_rope_patch_passes_real_judge(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id=f"oracle_rope_{uuid.uuid4().hex[:8]}",
        env="rope",
        difficulty=",".join(["easy"] * 8),
        seed=0,
        max_steps=1,
        sandbox="local",
        keep_images=False,
        keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    workspace = Path(state["workspace"])
    rope = workspace / "rope.py"
    source = rope.read_text(encoding="utf-8")
    assert "torch.arange(seq_len, device=device)" in source
    assert "return torch.cat((-x2, x1), dim=-1)" in source
    rope.write_text(
        source.replace(
            "torch.arange(seq_len, device=device)",
            "torch.arange(offset, offset + seq_len, device=device)",
        ).replace(
            "return torch.cat((-x2, x1), dim=-1)",
            "return torch.stack((-x[..., 1::2], x[..., 0::2]), dim=-1).flatten(-2)",
        ), encoding="utf-8",
    )
    attention = workspace / "attention.py"
    source = attention.read_text(encoding="utf-8")
    assert "offset = 0" in source
    attention.write_text(source.replace("offset = 0", "offset = cache.position_offset()"), encoding="utf-8")
    cache = workspace / "cache.py"
    source = cache.read_text(encoding="utf-8")
    assert "return 0" in source and "self.tokens_seen = self.tokens_seen" in source
    cache.write_text(
        source.replace("return 0", "return self.tokens_seen").replace(
            "self.tokens_seen = self.tokens_seen", "self.tokens_seen += int(chunk_len)"
        ), encoding="utf-8",
    )
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 1.0, info
    result = info["judge_result"]
    assert result["verdict"] == "PASS"
    assert result["metrics"]["passed_hidden_checks"] == result["metrics"]["total_hidden_checks"] == 5
    assert result["failure_mode"] == "pass"


def test_moco_probe_detects_real_logit_temperature_and_queue_fixes():
    torch = pytest.importorskip("torch")
    name = f"_episode_env_moco_oracle_{uuid.uuid4().hex[:8]}"
    output = ROOT / name
    try:
        proc = subprocess.run(
            [sys.executable, "generate_env.py", "--env", "moco", "--name", name,
             "--difficulty", "easy,easy,easy,easy,easy,easy", "--seed", "0"],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        workspace = output / "agent" / "workspace"
        judge_tree = ast.parse((output / "judge" / "judge.py").read_text(encoding="utf-8"))
        probe = next(
            node.value.value for node in judge_tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "PROBE_MODULE_TEMPLATE"
        )
        eval_script = workspace / "_eval_runner.py"
        eval_script.write_text(probe, encoding="utf-8")
        model_path = workspace / "moco_model.py"
        model_source = model_path.read_text(encoding="utf-8")
        queue_path = workspace / "queue_ops.py"
        queue_source = queue_path.read_text(encoding="utf-8")
        torch.manual_seed(123)
        torch.save(torch.randn(4, 1, 16, 16), workspace / "eval_train_inputs.pt")
        torch.save(torch.randn(3, 1, 16, 16), workspace / "eval_test_inputs.pt")
        for corrected, expected in ((False, False), (True, True)):
            if corrected:
                assert "logits = torch.cat([l_pos, l_neg], dim=1)" in model_source
                model_path.write_text(
                    model_source.replace(
                        "logits = torch.cat([l_pos, l_neg], dim=1)",
                        "logits = torch.cat([l_pos, l_neg], dim=1) / self.tau",
                    ), encoding="utf-8",
                )
                queue_path.write_text(
                    queue_source.replace(
                        "queue[:, start:start + n] = keys.T",
                        "queue[:, (torch.arange(n) + start) % k] = keys.T",
                    ), encoding="utf-8",
                )
            init = subprocess.run(
                [sys.executable, "-c", "import torch; from moco_model import MoCo; "
                 "torch.manual_seed(11); torch.save(MoCo(dim=16, K=512).state_dict(), 'ckpt.pt')"],
                cwd=workspace, capture_output=True, text=True, timeout=45,
            )
            assert init.returncode == 0, init.stderr
            scored = subprocess.run(
                [sys.executable, str(eval_script), str(workspace), "moco_model", "MoCo", "512"],
                cwd=workspace, capture_output=True, text=True, timeout=45,
            )
            assert scored.returncode == 0, scored.stderr
            outputs = torch.load(workspace / "eval_outputs.pt", weights_only=True)
            assert outputs["tau_ok"] is expected
            assert outputs["queue_wrap_ok"] is expected
    finally:
        shutil.rmtree(output, ignore_errors=True)


def test_known_good_moco_patch_passes_real_judge(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id=f"oracle_moco_{uuid.uuid4().hex[:8]}",
        env="moco",
        difficulty=",".join(["easy"] * 6),
        seed=0,
        max_steps=1,
        sandbox="local",
        keep_images=False,
        keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    workspace = Path(state["workspace"])
    model = workspace / "moco_model.py"
    source = model.read_text(encoding="utf-8")
    assert "logits = torch.cat([l_pos, l_neg], dim=1)" in source
    model.write_text(
        source.replace(
            "logits = torch.cat([l_pos, l_neg], dim=1)",
            "logits = torch.cat([l_pos, l_neg], dim=1) / self.tau",
        ), encoding="utf-8",
    )
    queue = workspace / "queue_ops.py"
    source = queue.read_text(encoding="utf-8")
    assert "queue[:, start:start + n] = keys.T" in source
    queue.write_text(
        source.replace(
            "queue[:, start:start + n] = keys.T",
            "queue[:, (torch.arange(n) + start) % k] = keys.T",
        ), encoding="utf-8",
    )
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and score == 1.0, info
    result = info["judge_result"]
    assert result["verdict"] == "PASS"
    assert result["failure_mode"] == "pass"
    assert result["checks"]["temperature_sensitive"] is True
    assert result["checks"]["queue_wraparound"] is True


def test_moco_full_credit_requires_both_named_fixes():
    judge = (ROOT / "envs" / "moco" / "files" / "judge.py").read_text(encoding="utf-8")
    assert "anti_gaming_passed = non_collapsed and tau_ok and queue_wrap_ok" in judge
    assert "baseline(train_in[:2], train_in[:2])" in judge
    assert "altered(train_in[:2], train_in[:2])" in judge
