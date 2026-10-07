"""Target integration tests for the accepted finite epistemic task family."""

from __future__ import annotations

import contextlib
import copy
import difflib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))

generate_env = importlib.import_module("generate_env")
task_engine = importlib.import_module("task_engine")
epistemic_relations = importlib.import_module("epistemic_relations")
GeneralModel = epistemic_relations.EpistemicModel
S5EpistemicModel = epistemic_relations.S5EpistemicModel
World = epistemic_relations.World
public_announcements = importlib.import_module("public_announcements")
atom = public_announcements.atom
knows = public_announcements.knows
neg = public_announcements.neg

VARIANTS = tuple(task_engine.VARIANT_TITLES)


def test_registered_config_and_supported_axes() -> None:
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert registry["environments"]["epistemic_reasoning"] == "envs/epistemic_reasoning/config.yaml"
    config = generate_env.load_config("epistemic_reasoning")
    assert [axis["id"] for axis in config["axes"]] == ["variant", "size"]
    assert set(config["axes"][0]["levels"]) == set(VARIANTS)
    assert set(config["axes"][1]["levels"]) == {"compact", "expanded"}
    assert config["scoring"] == {"mode": "check_fraction", "total_checks": 2}


def test_exact_fraction_and_formula_serialization_adapters() -> None:
    for value in (Fraction(0), Fraction(1, 7), Fraction(-5, 9), Fraction(12, 8)):
        encoded = task_engine.encode_fraction(value)
        assert task_engine.decode_fraction(encoded) == value
        assert type(task_engine.decode_fraction(encoded)) is Fraction
    for invalid in (0.5, "0.5", "2/4", "1/-2", "1/0", "01/2", True):
        with pytest.raises(task_engine.TaskSpecError):
            task_engine.decode_fraction(invalid)

    public = task_engine.build_instance("announcement_unpointed", "compact", 9)["public"]
    model = task_engine.propositional_model_from_json(public)
    p = atom("p")
    source_formulas = {
        "atom": p,
        "neg": neg(p),
        "knows": knows("A", p),
        "nested": knows("A", neg(knows("B", p))),
        "negated_knowledge": neg(knows("B", p)),
    }
    formula_specs = {
        "atom": {"atom": "p"},
        "neg": {"neg": {"atom": "p"}},
        "knows": {"knows": {"agent": "A", "formula": {"atom": "p"}}},
        "nested": {
            "knows": {
                "agent": "A",
                "formula": {"neg": {"knows": {"agent": "B", "formula": {"atom": "p"}}}},
            }
        },
        "negated_knowledge": {"neg": {"knows": {"agent": "B", "formula": {"atom": "p"}}}},
    }
    ids = [world["id"] for world in public["worlds"]]
    for name, spec in formula_specs.items():
        encoded_ast = task_engine.serialize_formula(spec)
        decoded_formula = task_engine.formula_from_json(encoded_ast)
        for world in ids:
            adapted = decoded_formula(model, world)
            direct = source_formulas[name](model, world)
            assert type(adapted) is bool
            assert adapted is direct

    for invalid in (
        {"call": "eval"},
        {"atom": "p", "neg": {"atom": "q"}},
        {"knows": {"agent": "A", "formula": {"atom": "p"}, "extra": 1}},
    ):
        with pytest.raises(task_engine.TaskSpecError):
            task_engine.serialize_formula(invalid)


def test_json_adapters_preserve_general_relation_and_s5_distinction() -> None:
    worlds = [World("w0", {"p": False}), World("w1", {"p": True})]
    general = GeneralModel(worlds, ["A"])
    assert general.accessible("A", "w0") == frozenset()
    assert general.knows("A", "w0", lambda world: world.properties["p"]) is True
    general.add_relation("A", "w0", "w1")
    assert general.accessible("A", "w0") == frozenset({"w1"})
    assert general.accessible("A", "w1") == frozenset()
    assert general.knows("A", "w0", lambda world: world.properties["p"]) is True

    with pytest.raises(ValueError):
        S5EpistemicModel(worlds, {"A": [{"w1"}]})
    valid_s5 = S5EpistemicModel(worlds, {"A": [{"w0", "w1"}]})
    assert valid_s5.accessible("A", "w0") == frozenset({"w0", "w1"})
    assert valid_s5.knows("A", "w0", lambda world: world.properties["p"]) is False


def test_seeded_oracles_cover_each_variant_and_size_without_leaking_answers() -> None:
    for variant in VARIANTS:
        for size in ("compact", "expanded"):
            first = task_engine.build_instance(variant, size, 37)
            second = task_engine.build_instance(variant, size, 37)
            assert first == second
            public = json.loads(json.dumps(first["public"]))
            assert "expected_answer" not in public
            assert "seed" not in public
            assert task_engine.evaluate_public_task(variant, public) == first["expected_answer"]
            errors = task_engine.validate_answer(
                variant, task_engine.answer_template(variant, public), public
            )
            assert not errors
            assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    compact = task_engine.build_instance("information_pool", "compact", 37)
    expanded = task_engine.build_instance("information_pool", "expanded", 37)
    assert len(compact["public"]["worlds"]) == 4
    assert len(expanded["public"]["worlds"]) == 8


def test_unpointed_and_checked_announcements_are_not_conflated() -> None:
    for seed in range(20):
        unpointed = task_engine.build_instance("announcement_unpointed", "compact", seed)
        checked = task_engine.build_instance("announcement_checked", "compact", seed)
        unpointed_answer = unpointed["expected_answer"]
        checked_answer = checked["expected_answer"]
        assert "actual_world" not in unpointed["public"]
        assert "actual_world" in checked["public"]
        if checked_answer["accepted"] is False:
            assert unpointed_answer["worlds"]
            break
    else:
        raise AssertionError("expected a checked sequence rejected at the actual world")

    public = {
        "variant": "announcement_unpointed",
        "worlds": [
            {"id": "w0", "valuation": ["p", "q"]},
            {"id": "w1", "valuation": ["p"]},
            {"id": "w2", "valuation": ["q"]},
        ],
        "partitions": {
            "A": [["w0", "w1"], ["w2"]],
            "B": [["w0"], ["w1", "w2"]],
        },
        "formula_sequence": [],
    }
    model = task_engine.propositional_model_from_json(public)
    from public_announcements import announce_sequence

    forward = announce_sequence(model, [atom("p"), knows("B", atom("p"))])
    reverse = announce_sequence(model, [knows("B", atom("p")), atom("p")])
    assert forward.worlds == frozenset({"w0", "w1"})
    assert reverse.worlds == frozenset({"w0"})
    assert model.worlds == frozenset({"w0", "w1", "w2"})


def test_silence_and_information_adapters_snapshot_inputs_and_keep_contracts() -> None:
    worlds = ["w0", "w1"]
    rows = {"A": {"w0": True, "w1": False}}
    protocol = task_engine.deterministic_protocol_from_json(worlds, rows)
    rows["A"]["w0"] = False
    assert protocol["A"]("w0") is True
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.deterministic_protocol_from_json(worlds, {"A": {"w0": 1, "w1": False}})
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.deterministic_protocol_from_json(worlds, {"A": {"w0": True}})

    no_rules = task_engine.build_instance("silence_empty_protocol", "expanded", 12)
    assert no_rules["public"]["protocol"] == {}
    assert no_rules["expected_answer"]["posterior"] == no_rules["public"]["prior"]

    pooled = task_engine.build_instance("information_pool", "expanded", 6)
    empty = task_engine.build_instance("information_empty_group", "compact", 6)
    assert len(pooled["expected_answer"]["pooled"]) == 1
    assert empty["expected_answer"]["pooled"] == [w["id"] for w in empty["public"]["worlds"]]


def test_invalid_task_and_answer_inputs_are_rejected() -> None:
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.build_instance("unknown", "compact", 0)
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.build_instance("event_sparse", "giant", 0)
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.build_instance("event_sparse", "compact", True)

    strict = task_engine.build_instance("event_strict", "compact", 4)
    malformed = copy.deepcopy(strict["public"])
    malformed["event"]["likelihoods"].pop(next(iter(malformed["prior"])))
    with pytest.raises(ValueError):
        task_engine.evaluate_public_task("event_strict", malformed)

    bad_policy = copy.deepcopy(task_engine.build_instance("policy_strict", "compact", 4)["public"])
    bad_policy["policy"][next(iter(bad_policy["policy"]))].pop("other")
    with pytest.raises(ValueError):
        task_engine.evaluate_public_task("policy_strict", bad_policy)

    announcement = task_engine.build_instance("announcement_unpointed", "compact", 4)["public"]
    bad_partition = copy.deepcopy(announcement)
    bad_partition["partitions"]["A"] = [[bad_partition["worlds"][0]["id"]]]
    with pytest.raises(ValueError):
        task_engine.propositional_model_from_json(bad_partition)

    checked = task_engine.build_instance("announcement_checked", "compact", 4)["public"]
    bad_actual = copy.deepcopy(checked)
    bad_actual["actual_world"] = "not-a-world"
    with pytest.raises(ValueError):
        task_engine.evaluate_public_task("announcement_checked", bad_actual)

    valid_task = task_engine.build_instance("s5_knowledge", "compact", 2)["public"]
    assert task_engine.validate_answer("s5_knowledge", {"truth": 1}, valid_task)
    assert task_engine.validate_answer("s5_knowledge", {"truth": True, "extra": 0}, valid_task)
    posterior_task = task_engine.build_instance("event_strict", "compact", 1)["public"]
    invalid_posterior = {"posterior": dict.fromkeys(posterior_task["prior"], "0/1")}
    assert any(
        "sum exactly to one" in error
        for error in task_engine.validate_answer("event_strict", invalid_posterior, posterior_task)
    )


def _make_answer_source(original: str, answer: dict) -> str:
    prefix = original.split("ANSWER =", 1)[0]
    return prefix + "# target integration candidate\nANSWER = " + repr(answer) + "\n"


def _wrong_but_well_formed_answer(expected: dict, public: dict) -> dict:
    wrong = copy.deepcopy(expected)
    if "posterior" in wrong:
        posterior = expected["posterior"]
        worlds = list(posterior)
        certain_worlds = {
            world for world, value in posterior.items() if task_engine.decode_fraction(value) == 1
        }
        alternative = next((world for world in worlds if world not in certain_worlds), worlds[-1])
        wrong["posterior"] = dict.fromkeys(worlds, "0/1")
        wrong["posterior"][alternative] = "1/1"
        if wrong["posterior"] == posterior:
            alternative = next(world for world in worlds if world != alternative)
            wrong["posterior"] = dict.fromkeys(worlds, "0/1")
            wrong["posterior"][alternative] = "1/1"
    elif "truth" in wrong:
        wrong["truth"] = not wrong["truth"]
    elif "accepted" in wrong:
        wrong["accepted"] = not wrong["accepted"]
        if wrong["accepted"]:
            wrong["worlds"] = [public["actual_world"]]
        else:
            wrong["worlds"] = None
    elif "worlds" in wrong:
        wrong["worlds"] = [] if expected["worlds"] else [public["worlds"][0]["id"]]
    elif "equilibria" in wrong:
        if expected["equilibria"]:
            wrong["equilibria"] = expected["equilibria"][1:]
        else:
            wrong["equilibria"] = [
                {
                    agent: dict.fromkeys(public["types"][agent], public["actions"][agent][0])
                    for agent in public["agents"]
                }
            ]
    else:
        wrong["individual"] = []
    return wrong


def _run_generated_judge(output: Path, workspace: Path, answer: dict, patch_path: Path):
    original = (workspace / "answer.py").read_text(encoding="utf-8")
    revised = _make_answer_source(original, answer)
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            revised.splitlines(keepends=True),
            fromfile="a/answer.py",
            tofile="b/answer.py",
        )
    )
    patch_path.write_text(patch, encoding="utf-8")
    env = os.environ.copy()
    env["JUDGE_PATCH_PATH"] = str(patch_path)
    env["JUDGE_ORIGINALS_DIR"] = str(workspace)
    return subprocess.run(
        [sys.executable, str(output / "judge" / "judge.py")],
        cwd=output / "judge",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_normal_generation_visible_tests_and_judge_scoring(
    tmp_path: Path, monkeypatch, variant: str
) -> None:
    monkeypatch.chdir(ROOT)
    name = f"_test_epistemic_{tmp_path.name}_{variant}"
    output = ROOT / name
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            generate_env.generate_env(
                "epistemic_reasoning", name, {"variant": variant, "size": "compact"}, seed=23
            )
        workspace = output / "agent" / "workspace"
        public = json.loads((workspace / "task.json").read_text(encoding="utf-8"))
        instance = task_engine.build_instance(variant, "compact", 23)
        assert public == instance["public"]
        assert (output / "run_eval.sh").is_file()
        assert (output / "judge" / "task_engine.py").is_file()
        for path in output.rglob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

        visible = subprocess.run(
            [sys.executable, str(workspace / "visible_tests.py")],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert visible.returncode == 0, visible.stdout + visible.stderr

        correct = _run_generated_judge(
            output, workspace, instance["expected_answer"], tmp_path / f"{variant}.correct.patch"
        )
        correct_result = json.loads(correct.stdout)
        assert correct.returncode == 0, correct.stdout + correct.stderr
        assert correct_result["verdict"] == "PASS"
        assert correct_result["score"] == 1.0
        assert correct_result["checks"]["answer_schema_valid"] is True
        assert correct_result["checks"]["answer_exactly_correct"] is True
        assert correct_result["checks"]["provenance_ok"] is True

        wrong_answer = _wrong_but_well_formed_answer(instance["expected_answer"], public)
        assert not task_engine.validate_answer(variant, wrong_answer, public)
        wrong = _run_generated_judge(
            output, workspace, wrong_answer, tmp_path / f"{variant}.wrong.patch"
        )
        wrong_result = json.loads(wrong.stdout)
        assert wrong.returncode == 1
        assert wrong_result["verdict"] == "FAIL"
        assert wrong_result["score"] == 0.5
        assert wrong_result["checks"]["answer_schema_valid"] is True
        assert wrong_result["checks"]["answer_exactly_correct"] is False

        invalid_answer = (
            {"truth": 1} if "truth" in instance["expected_answer"] else {"posterior": {}}
        )
        invalid = _run_generated_judge(
            output, workspace, invalid_answer, tmp_path / f"{variant}.invalid.patch"
        )
        invalid_result = json.loads(invalid.stdout)
        assert invalid.returncode == 1
        assert invalid_result["score"] == 0.0
        assert invalid_result["checks"]["answer_schema_valid"] is False
    finally:
        shutil.rmtree(output, ignore_errors=True)


def test_cli_generation_is_reproducible(tmp_path: Path) -> None:
    names = [f"_epistemic_cli_{tmp_path.name}_{index}" for index in range(2)]
    try:
        for name in names:
            proc = subprocess.run(
                [
                    sys.executable,
                    "generate_env.py",
                    "--env",
                    "epistemic_reasoning",
                    "--name",
                    name,
                    "--difficulty",
                    "policy_strict,expanded",
                    "--seed",
                    "91",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
        generated = [ROOT / name for name in names]
        assert (generated[0] / "agent/workspace/task.json").read_bytes() == (
            generated[1] / "agent/workspace/task.json"
        ).read_bytes()
        assert (generated[0] / "judge/instance_spec.py").read_bytes() == (
            generated[1] / "judge/instance_spec.py"
        ).read_bytes()
        assert (generated[0] / "run_eval.sh").is_file()
    finally:
        for name in names:
            shutil.rmtree(ROOT / name, ignore_errors=True)


def test_env_runner_reset_step_and_submit_for_new_family(tmp_path: Path) -> None:
    episode = f"epr_{tmp_path.name}"
    episode_dir = ROOT / ".episodes" / episode
    generated_name = f"_episode_env_{episode.replace('-', '_')}"
    try:
        reset = subprocess.run(
            [
                sys.executable,
                "env_runner.py",
                "reset",
                "--env",
                "epistemic_reasoning",
                "--episode-id",
                episode,
                "--difficulty",
                "announcement_checked,compact",
                "--seed",
                "23",
                "--max-steps",
                "5",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert reset.returncode == 0, reset.stdout + reset.stderr
        state = json.loads(reset.stdout)
        assert state["info"]["patchable_files"] == ["answer.py"]
        assert state["info"]["required_files"] == ["answer.py"]
        workspace = Path(state["info"]["workspace"])
        public = json.loads((workspace / "task.json").read_text(encoding="utf-8"))
        expected = task_engine.build_instance("announcement_checked", "compact", 23)[
            "expected_answer"
        ]

        write = subprocess.run(
            [
                sys.executable,
                "env_runner.py",
                "step",
                "--episode",
                episode,
                "--action",
                json.dumps(
                    {
                        "type": "write_file",
                        "path": "answer.py",
                        "content": _make_answer_source(
                            (workspace / "answer.py").read_text(), expected
                        ),
                    }
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert write.returncode == 0, write.stdout + write.stderr

        visible = subprocess.run(
            [
                sys.executable,
                "env_runner.py",
                "step",
                "--episode",
                episode,
                "--action",
                json.dumps({"cmd": f"{sys.executable} visible_tests.py"}),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert visible.returncode == 0, visible.stdout + visible.stderr
        assert "Visible answer-format checks passed" in json.loads(visible.stdout)["observation"]

        submitted = subprocess.run(
            [
                sys.executable,
                "env_runner.py",
                "step",
                "--episode",
                episode,
                "--action",
                json.dumps({"type": "submit", "confirm": True}),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert submitted.returncode == 0, submitted.stdout + submitted.stderr
        result = json.loads(submitted.stdout)
        assert result["done"] is True
        assert result["reward"] == 1.0
        assert result["info"]["judge_result"]["failure_mode"] == "pass"
        assert public["variant"] == "announcement_checked"
    finally:
        shutil.rmtree(episode_dir, ignore_errors=True)
        shutil.rmtree(ROOT / generated_name, ignore_errors=True)
