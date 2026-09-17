from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from arena.trajectory import make_messages, normalize_answer, score_answer
from arena.trajectory_runner import parse_seed_range
from shared.trajectory_semantics import certify_system_pair, make_case

ROOT = Path(__file__).resolve().parents[1]


def test_relay_certification_is_independent_and_relabeling_stable():
    for seed in (0, 1, 7):
        certificate = certify_system_pair(seed)
        assert certificate.certified
        first = make_case(
            semantic_seed=seed,
            representation="flat",
            witness_state="valid",
            query_type="complete_return",
            horizon=6,
            relabeling="canonical",
            certification=certificate.as_dict(),
        )
        second = make_case(
            semantic_seed=seed,
            representation="reflective",
            witness_state="valid",
            query_type="complete_return",
            horizon=6,
            relabeling="permuted_templates",
            certification=certificate.as_dict(),
        )
        assert first.control_bundle_id == second.control_bundle_id
        assert first.expected_answer == "yes"
        assert second.expected_answer == "yes"
        assert first.witness_applicable is (seed == 0)
        broken = make_case(
            semantic_seed=seed,
            representation="flat",
            witness_state="broken",
            query_type="complete_return",
            horizon=6,
            relabeling="canonical",
            certification=certificate.as_dict(),
        )
        if seed == 0:
            assert broken.expected_answer == "no"
            assert broken.stale_witness_prediction == "yes"
        else:
            assert broken.stale_witness_prediction is None


def test_resource_protocols_are_explicit_and_answers_are_normalized():
    case = make_case(
        semantic_seed=0,
        representation="flat",
        witness_state="valid",
        query_type="state_at_T",
        horizon=30,
        relabeling="canonical",
        resource_protocol="external_scratchpad",
        certification=certify_system_pair(0).as_dict(),
    )
    assert "scratchpad" in make_messages(case, "external_scratchpad")[0]["content"]
    assert normalize_answer("FINAL: A(0)\n") == "a(0)"
    score = score_answer(case, f"FINAL: {case.expected_answer}")
    assert score["correct"] is True
    assert score["matched_stale_witness_prediction"] is False


def test_seed_range_is_inclusive():
    assert parse_seed_range("0:2,7") == [0, 1, 2, 7]


def test_trajectory_environments_generate_and_compile():
    names = ["pytest_ts_parse", "pytest_ts_one", "pytest_ts_trajectory"]
    cases = [
        ("ts_parse_only", "valid,flat"),
        ("ts_one_step", "broken,reflective"),
        ("ts_trajectory", "valid,flat"),
    ]
    try:
        for name, (environment, difficulty) in zip(names, cases, strict=True):
            subprocess.run(["rm", "-rf", name], cwd=ROOT, check=False)
            result = subprocess.run(
                [
                    sys.executable,
                    "generate_env.py",
                    "--env",
                    environment,
                    "--name",
                    name,
                    "--difficulty",
                    difficulty,
                    "--seed",
                    "11",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            generated = ROOT / name
            assert (generated / "agent/workspace/prompt.md").is_file()
            assert (generated / "judge/judge.py").is_file()
            files = [str(path) for path in generated.rglob("*.py")]
            subprocess.run([sys.executable, "-m", "py_compile", *files], check=True)
            contents = "\n".join(
                path.read_text(errors="ignore") for path in generated.rglob("*") if path.is_file()
            )
            assert "%%" not in contents
    finally:
        for name in names:
            shutil.rmtree(ROOT / name, ignore_errors=True)


def test_offline_judge_scores_stale_witness_as_diagnostic(tmp_path):
    case = {
        "case_id": "broken-case",
        "query_type": "complete_return",
        "expected_answer": "no",
        "stale_witness_prediction": "yes",
        "initial_state": {"payload": "0"},
    }
    (tmp_path / "cases.jsonl").write_text(json.dumps(case) + "\n", encoding="utf-8")
    (tmp_path / "answers.jsonl").write_text(
        json.dumps({"case_id": "broken-case", "raw_model_output": "yes"}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "results.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "docker/trajectory_judge.py",
            "--cases",
            str(tmp_path / "cases.jsonl"),
            "--answers",
            str(tmp_path / "answers.jsonl"),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert '"accuracy": 0.0' in result.stdout
    scored = json.loads(output.read_text().splitlines()[0])
    assert scored["matched_stale_witness_prediction"] is True
    assert scored["correct"] is False
