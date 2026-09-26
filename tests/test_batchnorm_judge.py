"""Behavioral checks for the 100-class BN case and its eval-mode probe."""
from __future__ import annotations

import ast
import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_runner

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "envs/batchnorm_ema/files/train.py"
JUDGE = ROOT / "envs/batchnorm_ema/files/judge.py"


def test_hard_batchnorm_classes_have_distinct_generating_patterns():
    # Before the fix, every label y and y+24 had the same conditional image
    # distribution: only 24 distinguishable templates for 100 classes.
    def signature(label: int, *, higher_group: bool) -> tuple[int, ...]:
        col = (label * 11 + (5 * (label // 24) if higher_group else 0)) % 24
        return (label * 7 % 24, col, label % 3, label * 3 % 24)

    assert len({signature(y, higher_group=False) for y in range(100)}) == 24
    assert len({signature(y, higher_group=True) for y in range(100)}) == 100
    formula = "col = (label * 11 + 5 * (label // 24)) % 24"
    assert formula in TRAIN.read_text(encoding="utf-8")
    assert formula in JUDGE.read_text(encoding="utf-8")


def test_hard_batchnorm_data_is_classifiable_from_public_training_templates(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id="offline_bn_hard_data", env="batchnorm_ema",
        difficulty="hard,hard,hard,hard,hard", seed=0, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    workspace = Path(state["workspace"])
    judge_dir = Path(state["env_dir"]) / "judge"
    # A held-out nearest-template oracle, built solely from public training
    # images (no hidden labels), must clear the judge's 75% hard threshold.
    # The historical 24-template/100-label distribution scored ~30% here.
    script = '''import os, sys, torch
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from train import SyntheticCIFARDataset
from judge import generate_evaluation_data
workspace = sys.argv[2]
labels = generate_evaluation_data(workspace)
images = torch.load(os.path.join(workspace, "eval_inputs.pt"), weights_only=True)[:350]
train = SyntheticCIFARDataset(2500, 100, seed=1234, train=False)
indices = [int((train.labels == label).nonzero()[0]) for label in range(100)]
prototypes = (train.data[indices] - 0.5) / 0.5
predictions = torch.cdist(images.reshape(350, -1), prototypes.reshape(100, -1)).argmin(1)
print(float((predictions == labels[:350]).float().mean()))
'''
    proc = subprocess.run(
        [sys.executable, "-c", script, str(judge_dir), str(workspace)],
        cwd=workspace, env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    assert float(proc.stdout.strip()) >= 0.75


def test_hard_batchnorm_probe_catches_training_mode_bn_during_eval(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    args = SimpleNamespace(
        episode_id="offline_bn_hard_probe", env="batchnorm_ema",
        difficulty="hard,hard,hard,hard,hard", seed=0, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(args.episode_id)
    workspace = Path(state["workspace"])
    judge = Path(state["env_dir"]) / "judge/judge.py"
    tree = ast.parse(judge.read_text(encoding="utf-8"))
    probe = next(
        node.value.value for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "EVAL_PROBE"
    )
    (workspace / "_eval_runner.py").write_text(probe.format(workdir=str(workspace)))
    torch.manual_seed(99)
    torch.save(torch.randn(128, 3, 32, 32), workspace / "eval_inputs.pt")
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    initialize = subprocess.run(
        [sys.executable, "-c", "import torch; from model import ResNetBN; "
         "torch.save(ResNetBN().state_dict(), 'model.pth')"],
        cwd=workspace, env=env, capture_output=True, text=True, timeout=90,
    )
    assert initialize.returncode == 0, initialize.stderr

    def run_probe():
        proc = subprocess.run(
            [sys.executable, "_eval_runner.py"], cwd=workspace, env=env,
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        return torch.load(workspace / "eval_outputs.pt", weights_only=True)

    ghost = run_probe()
    assert ghost["has_bn"] is True
    assert ghost["bn_stats_frozen"] is False
    assert ghost["eval_consistent"] is False

    source_file = workspace / "model.py"
    source = source_file.read_text(encoding="utf-8")
    start = source.index("    def train(self, mode=True):")
    end = source.index("\n\ndef load_model", start)
    source_file.write_text(
        source[:start] + "    def train(self, mode=True):\n        return super().train(mode)\n" + source[end:],
        encoding="utf-8",
    )
    fixed = run_probe()
    assert fixed["has_bn"] is True
    assert fixed["bn_stats_frozen"] is True
    assert fixed["batch_independent"] is True
    assert fixed["eval_consistent"] is True
    assert "anti_gaming_passed = coverage_ok and running_stats_ok and eval_consistent" in JUDGE.read_text()
