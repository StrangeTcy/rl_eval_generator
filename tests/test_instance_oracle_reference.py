"""Exact-instance references must apply on every axis value the generator can emit.

`tools/instance_oracle_gate.py` certifies a case by patching its workspace three ways and
checking that the reference passes, the untouched instance fails, and the plausible-wrong variant
fails in the predicted place. Its glyph reference selected the optimizer by exact text, and
glyph's `optimizer` axis *chooses that text* - so only `easy` vectors were patchable, and the
strength-2 pairwise campaign blocked on `oracle_error` for the rest, before any provider call.
That is the failure this file pins: not the env, not the campaign, the reference's own matching.
moco's reference carried the same disease in a different axis - it opened `moco_model.py` by name,
and `naming` renames that file - while rope and glyph fail on vectors whose masked symptom the
reference would only re-introduce. All three are checked here against real generated instances.

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
from tools.instance_oracle_gate import (  # noqa: E402
    _GLYPH_EVAL_IMG_SIZE, _glyph, _glyph_augmentation, _glyph_optimizer, _moco, _rope,
)

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


def _generate(tmp: Path, env: str, levels: list[str], interventions: str = "") -> tuple[Path, str]:
    """A real generated workspace, at exactly the vector named, without the judge."""
    episode_id = "oracle_" + uuid.uuid4().hex[:16]
    old_dir = env_runner.EPISODES_DIR
    try:
        env_runner.EPISODES_DIR = tmp / "episodes"
        args = SimpleNamespace(
            episode_id=episode_id, env=env, difficulty=",".join(levels), seed=0,
            max_steps=1, sandbox="local", keep_images=False, keep_workspace=True,
            interventions=interventions,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            env_runner.reset(args)
        state = env_runner._load_state(episode_id)
    finally:
        env_runner.EPISODES_DIR = old_dir
    return Path(state["workspace"]), episode_id


# envs/moco/config.yaml axis order; `naming` is the one that renames the model module.
MOCO_EASY = ["easy"] * 6
GLYPH_EASY = ["easy"] * 6
ROPE_EASY = ["easy"] * 8


@pytest.mark.parametrize("naming", ["easy", "medium", "hard"])
def test_the_moco_reference_patches_the_file_the_naming_axis_chose(tmp_path: Path, naming: str) -> None:
    """`naming` writes the model into moco_model.py only at easy: medium renames it contrastive.py
    and hard engine.py. Opening a literal filename is why 65 of 90 gated moco cases died with
    FileNotFoundError inside the gate, and why the file has to be found by its content."""
    workspace, _ = _generate(tmp_path, "moco", [naming] + MOCO_EASY[1:])
    files_before = {p.name: p.read_text(encoding="utf-8") for p in workspace.glob("*.py")}
    _moco(workspace, wrong=False)
    changed = {name for name, text in files_before.items()
               if (workspace / name).read_text(encoding="utf-8") != text}
    assert "queue_ops.py" in changed
    patched = [name for name in changed if name != "queue_ops.py"]
    assert len(patched) == 1, f"naming={naming}: the model edit landed in {sorted(changed)}"
    source = (workspace / patched[0]).read_text(encoding="utf-8")
    assert source.count("logits = torch.cat([l_pos, l_neg], dim=1) / self.tau") == 1
    ast.parse(source)


def test_the_moco_reference_follows_the_terminology_intervention(tmp_path: Path) -> None:
    """terminology renames the module again (envs/moco/config.yaml:208-222), so an easy-naming
    vector under this intervention failed for the same reason its medium/hard siblings did."""
    workspace, _ = _generate(tmp_path, "moco", MOCO_EASY, interventions="terminology")
    _moco(workspace, wrong=True)
    names = [p.name for p in workspace.glob("*.py")
             if "logits = torch.cat([l_pos, l_neg], dim=1) / 1.0" in p.read_text(encoding="utf-8")]
    assert names == ["retrieval_pooled_encoder.py"]


def test_an_ambiguous_moco_target_is_refused_not_guessed(tmp_path: Path) -> None:
    """Two candidate files means the generator changed shape; picking one would certify a patch
    that is not the reference anyone read."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    line = "        logits = torch.cat([l_pos, l_neg], dim=1)\n"
    body = "class M:\n    def forward(self):\n" + line
    for name in ("moco_model.py", "engine.py"):
        (workspace / name).write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one moco logits concatenation"):
        _moco(workspace, wrong=False)


def test_the_rope_reference_refuses_a_vector_that_is_already_fixed(tmp_path: Path) -> None:
    """At symptom_mask=hard the cache offset is not masked, so rope's reference would be applying
    its own fix to a file that already carries it. It fails closed - and now says which axis."""
    workspace, _ = _generate(tmp_path, "rope", ROPE_EASY[:-1] + ["hard"])
    with pytest.raises(ValueError, match="cannot be certified"):
        _rope(workspace, wrong=False)


def test_the_rope_reference_still_reaches_a_masked_vector(tmp_path: Path) -> None:
    workspace, _ = _generate(tmp_path, "rope", ROPE_EASY)
    _rope(workspace, wrong=False)
    cache = (workspace / "cache.py").read_text(encoding="utf-8")
    assert "return self.tokens_seen" in cache and "return 0" not in cache
    ast.parse(cache)


@pytest.mark.parametrize("vector", [
    ["hard", "hard", "easy", "easy", "medium", "medium"],      # the crash the gate rows reported
    ["hard", "hard", "hard", "hard", "hard", "hard"],
    ["hard", "medium", "hard", "medium", "hard", "medium"],
    ["easy", "easy", "easy", "easy", "easy", "hard"],          # trap parked in forward instead
    ["medium", "easy", "medium", "easy", "hard", "hard"],
])
def test_the_glyph_reference_leaves_no_spatial_path_into_the_pooled_head(
    tmp_path: Path, vector: list[str]
) -> None:
    """`x = self.classifier(x)` must be the only thing standing between the features and the head.

    architecture=hard flattens inside its own encoder block, so a classifier that pools receives 2-D
    and training dies in F.adaptive_avg_pool2d; symptom_mask=hard parks `SpatialPool(size=4)` in
    `forward`, cropping the feature map to the training resolution. Both calls are spliced out with
    the classifier, so the pooled head is reached by nothing but the feature stack - and the gate
    rows say that half worked: at these vectors the reference reported `spatial_invariance_learned`
    and `anti_gaming_passed` green. What it did not do was reach `pass_threshold`, because
    `overfit_spatial_layout` is emitted for a model that learned a stable mapping and still scores
    badly (envs/glyph/files/judge.py:110-113). That is the *data* half of symptom_mask=hard, pinned
    by test_the_reference_trains_on_the_canvas_the_judge_scores rather than by this splice.
    """
    workspace, _ = _generate(tmp_path, "glyph", vector)
    _glyph(workspace, wrong=False)
    source = (workspace / "model.py").read_text(encoding="utf-8")
    # The trap classes define their own `forward` above the model, so the model's is the last one.
    head = source[source.rindex("    def forward"):source.index("\ndef ", source.rindex("    def forward"))]
    body = [line.strip() for line in head.splitlines() if line.strip().startswith("x =")]
    assert body[:2] == ["x = self.features(x)", "x = self.classifier(x)"], body[:3]
    assert "SpatialPool(" not in head and "self.encoder(" not in head
    assert "nn.AdaptiveAvgPool2d((1, 1))" in source
    ast.parse(source)
    ast.parse((workspace / "train.py").read_text(encoding="utf-8"))


def test_a_forward_the_reference_cannot_read_is_refused(tmp_path: Path) -> None:
    """A trap the splice does not recognize stops the certification instead of being stepped over."""
    workspace, _ = _generate(tmp_path, "glyph", ["hard", "easy", "easy", "easy", "easy", "hard"])
    model = workspace / "model.py"
    model.write_text(
        model.read_text(encoding="utf-8").replace(
            "        x = SpatialPool(size=4)(x)", "        x = SpatialPool( size=4 )(x)"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="still leads into the classifier"):
        _glyph(workspace, wrong=False)


# --- the two data-pipeline traps the classifier splice cannot reach -----------------------------
#
# Twelve glyph rows blocked the Atria campaign's exact-instance gate with the reference scoring
# 0.059-0.271 while every check upstream of the metric was green. Neither of the two causes was in
# model.py, which is why a smarter splice could not have found them, and why the axis that decided
# the block was not `architecture`: `hard,hard,easy,easy,medium,medium` and
# `hard,hard,medium,medium,easy,easy` graded 1.0 unaided.

GLYPH_RED_HERRING_HARD = ["easy", "easy", "hard", "easy", "easy", "easy"]
GLYPH_SYMPTOM_MASK_HARD = ["easy", "easy", "easy", "easy", "easy", "hard"]
GLYPH_BOTH_TRAPS = ["hard", "hard", "hard", "hard", "hard", "hard"]


def test_the_reference_neutralises_the_always_inverting_augmentation(tmp_path: Path) -> None:
    """`p_invert = 0.1 + 1.0` is compared with `<`, so the training set is inverted in full and the
    judge's clean 64x64 set is a different distribution. Ten of the twelve blocked rows carried that
    signature; this is the repair, and it must not move the random stream."""
    workspace, _ = _generate(tmp_path, "glyph", GLYPH_RED_HERRING_HARD)
    dataset = workspace / "dataset.py"
    before = dataset.read_text(encoding="utf-8")
    assert "self.p_invert = 0.1 + 1.0" in before, "the vector no longer emits the defect"
    _glyph(workspace, wrong=False)
    after = dataset.read_text(encoding="utf-8")
    assert "self.p_invert = 0.1" in after and "0.1 + 1.0" not in after
    ast.parse(after)
    # The training canvas was never the problem at symptom_mask=easy: no gratuitous edit.
    assert "IMG_SIZE = 64" in after and "_glyph_dataset" not in (workspace / "train.py").read_text()


def test_the_reference_trains_on_the_canvas_the_judge_scores(tmp_path: Path) -> None:
    """symptom_mask=hard renders %%IMG_SIZE%% as 32 while the judge evaluates at 64 and shapes are
    drawn in absolute pixels. Two of the blocked rows failed with `overfit_spatial_layout` and green
    anti-gaming, which only a resolution mismatch produces. The edit belongs in train.py, because
    visible_tests.py asserts against the `IMG_SIZE` the agent's own dataset.py exports."""
    workspace, _ = _generate(tmp_path, "glyph", GLYPH_SYMPTOM_MASK_HARD)
    assert "IMG_SIZE = 32" in (workspace / "dataset.py").read_text(encoding="utf-8")
    _glyph(workspace, wrong=False)
    assert "IMG_SIZE = 32" in (workspace / "dataset.py").read_text(encoding="utf-8")
    train = (workspace / "train.py").read_text(encoding="utf-8")
    assert f"_glyph_dataset.IMG_SIZE = {_GLYPH_EVAL_IMG_SIZE}" in train
    assert "_glyph_dataset.IMG_SIZE = 32" not in train
    compile(train, "train.py", "exec")
    assert train.index("_glyph_dataset.IMG_SIZE") < train.index("def main()"), (
        "generate_glyph reads IMG_SIZE at call time, but the mutation still has to precede training"
    )


def test_the_reference_adds_nothing_where_no_defect_was_injected(tmp_path: Path) -> None:
    """A reference that repairs an absent bug is certifying its own edit, not the instance."""
    workspace, _ = _generate(tmp_path, "glyph", GLYPH_EASY)
    before = (workspace / "dataset.py").read_text(encoding="utf-8")
    _glyph(workspace, wrong=False)
    assert (workspace / "dataset.py").read_text(encoding="utf-8") == before
    assert "_glyph_dataset" not in (workspace / "train.py").read_text(encoding="utf-8")


def test_the_negative_control_keeps_both_data_defects(tmp_path: Path) -> None:
    """plausible_wrong must stay wrong *for the reason the env installed*: if the reference's data
    repairs leaked into the control, the gate would lose its discrimination silently."""
    workspace, _ = _generate(tmp_path, "glyph", GLYPH_BOTH_TRAPS)
    pristine = {path.name: path.read_text(encoding="utf-8") for path in workspace.glob("*.py")}
    _glyph(workspace, wrong=True)
    for name in ("dataset.py",):
        assert (workspace / name).read_text(encoding="utf-8") == pristine[name]
    train = (workspace / "train.py").read_text(encoding="utf-8")
    assert "_glyph_dataset" not in train and "IMG_SIZE = 32" in pristine["dataset.py"]


@pytest.mark.parametrize("line", ["self.p_invert = 0.2 + 1.0", "self.p_invert = ALWAYS"])
def test_an_unreadable_inversion_site_is_refused(tmp_path: Path, line: str) -> None:
    """An always-inverting augmentation this pattern cannot match would leave the reference training
    on the negative of its own evaluation set while reporting success."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "dataset.py").write_text(
        "class BuggyAugmentation:\n    def __init__(self):\n        " + line + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot read"):
        _glyph_augmentation(workspace, wrong=False)


def test_the_pinned_evaluation_canvas_still_matches_the_env(tmp_path: Path) -> None:
    """The reference hardcodes the judge's canvas because nothing in the workspace states it, so the
    config - not a guess - is what has to agree. If %%EVAL_IMG_SIZE%% ever moves, this fails and the
    reference is re-read instead of quietly training on the wrong distribution again."""
    import yaml

    config = yaml.safe_load((ROOT / "envs" / "glyph" / "config.yaml").read_text(encoding="utf-8"))
    axis = next(a for a in config["axes"] if a["id"] == "symptom_mask")
    sizes = {level: int(str(axis["levels"][level]["%%EVAL_IMG_SIZE%%"])) for level in axis["levels"]}
    assert set(sizes.values()) == {_GLYPH_EVAL_IMG_SIZE}, sizes
    assert int(str(axis["levels"]["hard"]["%%IMG_SIZE%%"])) < _GLYPH_EVAL_IMG_SIZE
