"""The glyph exact-instance reference must apply on every value of its `optimizer` axis.

`tools/instance_oracle_gate.py` certifies a case by patching its workspace three ways and
checking that the reference passes, the untouched instance fails, and the plausible-wrong variant
fails in the predicted place. Its glyph reference selected the optimizer by exact text, and
glyph's `optimizer` axis *chooses that text* - so only `easy` vectors were patchable, and the
strength-2 pairwise campaign blocked on `oracle_error` for the rest, before any provider call.
That is the failure this file pins: not the env, not the campaign, the reference's own matching.

The judge container is not available in this checkout, so the graded verdicts of the three
variants are still measured on a runner. What is provable here is the invariant that was
violated: the reference must be an intervention on the instance it certifies, for every vector
the generator can emit, and it must refuse rather than certify a no-op.
"""
from __future__ import annotations

import ast
import contextlib
import io
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402
from tools.instance_oracle_gate import _glyph, _glyph_optimizer  # noqa: E402

# What envs/glyph/config.yaml substitutes for %%OPT_LINE%%, per axis value.
AXIS_LINES = {
    "easy": "optimizer = optim.SGD(model.parameters(), lr=1e-5)  # extremely slow",
    "medium": "optimizer = optim.SGD(model.parameters(), lr=1e-4)",
    "hard": "optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.5)",
}
REFERENCE = "optimizer = optim.Adam(model.parameters(), lr=1e-3)"
TRAIN_STUB = (
    "import torch, torch.nn as nn, torch.optim as optim\n"
    "EPOCHS = 10\n"
    "def run(model, num_classes):\n"
    "    {line}\n"
    "    return optimizer\n"
)


def _workspace(tmp: Path, line: str) -> Path:
    workspace = tmp / "ws"
    workspace.mkdir(parents=True)
    (workspace / "train.py").write_text(TRAIN_STUB.format(line=line), encoding="utf-8")
    return workspace


@pytest.mark.parametrize("axis", sorted(AXIS_LINES))
def test_a_reference_applies_to_every_optimizer_axis_value(tmp_path: Path, axis: str) -> None:
    workspace = _workspace(tmp_path, AXIS_LINES[axis])
    _glyph_optimizer(workspace, wrong=False)
    source = (workspace / "train.py").read_text(encoding="utf-8")
    assert REFERENCE in source, f"the reference did not reach the {axis} spelling"
    assert AXIS_LINES[axis] not in source
    ast.parse(source)  # a reference that breaks the program certifies nothing


def test_a_reference_that_would_change_nothing_is_refused(tmp_path: Path) -> None:
    """The one thing the gate must never do is certify an instance that already carries the
    answer: a no-op reference would grade the untouched workspace as if the agent had worked."""
    workspace = _workspace(tmp_path, REFERENCE)
    with pytest.raises(ValueError, match="cannot be certified"):
        _glyph_optimizer(workspace, wrong=False)


@pytest.mark.parametrize("body", ["", "a = 1\nb = 2\n"])
def test_a_missing_or_ambiguous_optimizer_line_fails_closed(tmp_path: Path, body: str) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "train.py").write_text(
        "import torch.optim as optim\n" + body + (
            "optimizer = optim.SGD()\noptimizer = optim.Adam()\n" if body else ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not configured for this vector"):
        _glyph_optimizer(workspace, wrong=False)


def test_the_negative_control_may_coincide_with_the_pristine_line(tmp_path: Path) -> None:
    """`plausible_wrong` for an `optimizer=medium` vector *is* the pristine program. That is
    allowed, and only for the negative control: a control that equals the untouched instance fails
    the graded metric, which is the verdict demanded of it."""
    workspace = _workspace(tmp_path, AXIS_LINES["medium"])
    before = (workspace / "train.py").read_text(encoding="utf-8")
    _glyph_optimizer(workspace, wrong=True)
    assert (workspace / "train.py").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("axis", sorted(AXIS_LINES))
def test_the_generated_glyph_workspace_is_patchable_at_every_axis_value(tmp_path: Path, axis: str) -> None:
    """The regression itself, against real generated instances rather than a fixture."""
    levels = ["easy", axis, "easy", "easy", "easy", "easy"]
    episode_id = "oracle_" + uuid.uuid4().hex[:16]
    old_dir = env_runner.EPISODES_DIR
    try:
        env_runner.EPISODES_DIR = tmp_path / "episodes"
        args = SimpleNamespace(
            episode_id=episode_id, env="glyph", difficulty=",".join(levels), seed=0,
            max_steps=1, sandbox="local", keep_images=False, keep_workspace=True,
            interventions="",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            env_runner.reset(args)
        state = env_runner._load_state(episode_id)
        workspace = Path(state["workspace"])
        pristine = {p.name: p.read_text(encoding="utf-8") for p in workspace.glob("*.py")}
        _glyph(workspace, wrong=False)
        changed = {
            name for name, text in pristine.items()
            if (workspace / name).read_text(encoding="utf-8") != text
        }
    finally:
        env_runner.EPISODES_DIR = old_dir
    assert {"model.py", "train.py"} <= changed, (
        f"optimizer={axis}: the reference left {sorted(set(pristine) - changed)} untouched"
    )
    ast.parse((workspace / "train.py").read_text(encoding="utf-8"))
    ast.parse((workspace / "model.py").read_text(encoding="utf-8"))


def test_the_reference_is_readable_without_the_judge_dependency() -> None:
    """These tests are only a guard if the reference can be imported where there is no judge
    image. A helper that reached for the container at import time would silently drop this file to
    skips, which is how a gate loses its coverage without anyone editing the gate."""
    source = (ROOT / "tools" / "instance_oracle_gate.py").read_text(encoding="utf-8")
    block = source[source.index("def _glyph_optimizer") : source.index("def _glyph(")]
    assert "DockerBackend" not in block and "subprocess" not in block
    assert "import re" in source
