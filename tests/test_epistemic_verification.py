"""V1/V3 verification-track tests (Mission 02 portfolio, Batch 3).

V1 - Faithfulness of English renderings: from the public task.md alone, the
registered formal state and queried proposition reconstruct exactly
(predefined: any mismatch is a faithfulness failure; mechanical annotation,
no adjudication).

V3 - Feasibility of independent verification: tools/epistemic_verifier.py
recomputes every family's ground truth from the public text and the accepted
shared substrate only, never importing family generator code. Notably, the
E2 ground truth is recomputed WITHOUT the hidden actual world (restriction
sequence + public-derivability invariant).

Guards:
* surface-vocabulary drift between the verifier's data tables and family
  vocabularies (data identity, not logic sharing);
* tamper detection: a corrupted task text must fail reconstruction or
  verification (the verifier is not a rubber stamp);
* structural independence: the verifier module imports no family core.
"""
from __future__ import annotations

import importlib.util
import itertools
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import epistemic_verifier as VERIFIER  # noqa: E402


def _load_core(name: str, relpath: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


E2 = _load_core("ver_e2_core", "envs/epistemic_announcements/files/core.py")
E4 = _load_core("ver_e4_core", "envs/epistemic_nested_knowledge/files/core.py")
E5 = _load_core("ver_e5_core", "envs/epistemic_fragmented_observation/files/core.py")
E3 = _load_core("ver_e3_core", "envs/epistemic_silence/files/core.py")
E6 = _load_core("ver_e6_core", "envs/epistemic_type_games/files/core.py")

SEEDS = (0, 1, 2)

GRIDS = {
    "epistemic_type_games": [
        dict(types=t, payoffs=p, scenario=s, seed=seed)
        for t, p, s, seed in itertools.product(
            ("small", "large"), ("mild", "sharp"),
            ("expedition", "office"), SEEDS)
    ],
    "epistemic_announcements": [
        dict(worlds=w, depth=d, query=q, scenario=s, seed=seed)
        for w, d, q, s, seed in itertools.product(
            ("three", "four"), ("one", "chain"), ("factual", "nested"),
            ("expedition", "office"), SEEDS)
    ],
    "epistemic_nested_knowledge": [
        dict(worlds=w, order=o, scenario=s, seed=seed)
        for w, o, s, seed in itertools.product(
            ("four", "six"), ("first", "second", "third"),
            ("expedition", "office"), SEEDS)
    ],
    "epistemic_fragmented_observation": [
        dict(worlds=w, fragment=f, scenario=s, seed=seed)
        for w, f, s, seed in itertools.product(
            ("four", "six"), ("symmetric", "asymmetric"),
            ("expedition", "office"), SEEDS)
    ],
    "epistemic_silence": [
        dict(observation=o, protocol=p, prior=r, scenario=s, seed=seed)
        for o, p, r, s, seed in itertools.product(
            ("silence", "message"), ("single", "pair"), ("uniform", "skewed"),
            ("expedition", "office"), SEEDS)
    ],
}

CORES = {
    "epistemic_type_games": E6,
    "epistemic_announcements": E2,
    "epistemic_nested_knowledge": E4,
    "epistemic_fragmented_observation": E5,
    "epistemic_silence": E3,
}


def _instances(family: str):
    core = CORES[family]
    for kwargs in GRIDS[family]:
        yield core.build_instance(**kwargs)


def test_verifier_is_structurally_independent_of_generators() -> None:
    source = (ROOT / "tools" / "epistemic_verifier.py").read_text(encoding="utf-8")
    assert "epistemic_announcements/files" not in source
    assert "epistemic_nested_knowledge/files" not in source
    assert "epistemic_fragmented_observation/files" not in source
    assert "epistemic_silence/files" not in source
    assert "epistemic_type_games/files" not in source
    # Only the accepted substrate may drive recomputation.
    for forbidden in ("import core", "from core", "build_instance"):
        assert forbidden not in source


def test_surface_vocabulary_tables_match_family_vocabularies() -> None:
    # The verifier table is the union of the E2/E4/E5 surface vocabularies;
    # E2 uses 3-4 worlds (a prefix), E4/E5 use up to 6 (exact match).
    for scenario, vocab in E2.VOCAB.items():
        table = VERIFIER.E2_E4_E5_VOCAB[scenario]
        assert table.agent_names == vocab.agent_names
        assert table.world_labels[: len(vocab.world_labels)] == vocab.world_labels
        assert table.atom_texts == vocab.atom_texts
    for core in (E4, E5):
        for scenario, vocab in core.VOCAB.items():
            table = VERIFIER.E2_E4_E5_VOCAB[scenario]
            assert table.agent_names == vocab.agent_names
            assert table.world_labels == vocab.world_labels
            assert table.atom_texts == vocab.atom_texts
    for scenario, vocab in E3.VOCAB.items():
        table = VERIFIER.E3_VOCAB[scenario]
        assert table.agent_names == vocab.agent_names
        assert tuple(vocab.world_labels[w] for w in ("w1", "w2", "w3")) == \
            table.world_labels


def test_v1_exact_reconstruction_on_full_grids() -> None:
    total = 0
    for family in GRIDS:
        for inst in _instances(family):
            total += 1
            reconstruction, errors = VERIFIER.v1_reconstruct(
                inst.public_task_md(), family
            )
            assert not errors, f"{family} {inst.seed}: {errors}"
            mismatches = VERIFIER.v1_compare(reconstruction, inst.to_spec(), family)
            assert not mismatches, f"{family} {inst.to_spec()}: {mismatches}"
    assert total == 24 + 48 + 36 + 24 + 48  # 180 instances across the five grids


def test_v3_independent_verification_on_full_grids() -> None:
    for family in GRIDS:
        for inst in _instances(family):
            result = VERIFIER.v3_verify(inst.public_task_md(), inst.to_spec(), family)
            assert result["verified"], f"{family} {inst.to_spec()}: {result}"


def test_tampered_task_fails_reconstruction_or_verification() -> None:
    """The verifier must catch corrupted public text, not rubber-stamp it."""
    inst = E4.build_instance(worlds="six", order="second", scenario="office", seed=1)
    text = inst.public_task_md()
    spec = inst.to_spec()

    # Flip one valuation fact between the two atoms on some world line.
    tampered = text.replace(
        f"- `w1`", "- `w9`", 1
    )
    reconstruction, errors = VERIFIER.v1_reconstruct(tampered, "epistemic_nested_knowledge")
    mismatches = errors or VERIFIER.v1_compare(
        reconstruction, spec, "epistemic_nested_knowledge"
    )
    assert mismatches, "renamed world was not caught"

    # Delete the indistinguishability block entirely.
    stripped = text.split("Indistinguishability:")[0] + "\n## Scenario under evaluation"
    stripped += text.split("## Scenario under evaluation", 1)[1]
    reconstruction, errors = VERIFIER.v1_reconstruct(
        stripped, "epistemic_nested_knowledge"
    )
    mismatches = errors or VERIFIER.v1_compare(
        reconstruction, spec, "epistemic_nested_knowledge"
    )
    assert mismatches, "missing partitions were not caught"


def test_cli_verifies_generated_environment_end_to_end(tmp_path: Path) -> None:
    env_dir = ROOT / "smoke_verifier_cli"
    if env_dir.exists():
        shutil.rmtree(env_dir)
    try:
        completed = subprocess.run(
            [sys.executable, "generate_env.py", "--env", "epistemic_silence",
             "--name", "smoke_verifier_cli",
             "--difficulty", "silence,pair,skewed,office", "--seed", "2"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        exit_code = VERIFIER.main(["--dir", str(env_dir), "--mode", "both"])
        assert exit_code == 0
        # Corrupting the shipped task must flip the CLI exit code.
        task_path = env_dir / "agent" / "workspace" / "task.md"
        task_path.write_text(
            task_path.read_text(encoding="utf-8").replace("1/4", "1/9", 1),
            encoding="utf-8",
        )
        exit_code = VERIFIER.main(["--dir", str(env_dir), "--mode", "both"])
        assert exit_code == 1
    finally:
        if env_dir.exists():
            shutil.rmtree(env_dir)
