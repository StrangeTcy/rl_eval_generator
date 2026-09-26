import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_scoring_is_configured_in_environment_settings():
    """Scoring mechanics should be environment settings, not hardcoded policy."""
    for config_path in (ROOT / "envs").rglob("config.yaml"):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert "scoring" in config, f"missing scoring block in {config_path}"
        assert "mode" in config["scoring"]
        if config["scoring"]["mode"] == "continuous_accuracy":
            assert "pass_threshold" in config["scoring"]
            assert "partial_threshold" in config["scoring"]
        elif config["scoring"]["mode"] == "check_fraction":
            assert "total_checks" in config["scoring"]
        else:
            raise AssertionError(f"unknown scoring mode {config['scoring']['mode']!r}")


def test_judges_use_scoring_placeholders_from_config():
    judges = {
        path.parts[-3]: path.read_text(encoding="utf-8")
        for path in (ROOT / "envs").rglob("judge.py")
    }
    for env in ["glyph", "batchnorm_ema", "moco"]:
        assert "%%SCORING_PASS_THRESHOLD%%" in judges[env]
        assert "%%SCORING_PARTIAL_THRESHOLD%%" in judges[env]
        assert "score_from_accuracy(" in judges[env]

    rope = judges["rope"]
    assert "%%SCORING_TOTAL_CHECKS%%" in rope
    assert "passed / TOTAL_HIDDEN_CHECKS" in rope
    assert "passed_hidden_checks" in rope
    assert "total_hidden_checks" in rope


def test_all_check_fraction_judges_use_consistent_scoring():
    for config_path in (ROOT / "envs").rglob("config.yaml"):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if config["scoring"]["mode"] != "check_fraction":
            continue
        judge = (config_path.parent / "files" / "judge.py").read_text(encoding="utf-8")
        if config_path.parent.name == "rope":
            # RoPE records its own per-check events and already sets both fields.
            assert 'result["raw_accuracy"] = round(score, 6)' in judge
            assert "set_failure(result, FAILURE_UNDERFIT)" in judge
        else:
            assert "score_from_checks(result, checks, TOTAL_CHECKS)" in judge, config_path


def test_state_carry_batch_check_allows_only_roundoff():
    judge = (ROOT / "envs" / "recurrent_depth" / "state_carry" / "files" / "judge.py").read_text(encoding="utf-8")
    comparison = judge.split('checks["batch_independence"] = ', 1)[1].split("\n\n", 1)[0]
    assert "torch.allclose(" in comparison
    assert "rtol=1e-5" in comparison and "atol=1e-6" in comparison


def test_check_fraction_scoring_metadata_and_required_edits():
    # The generated judge_lib needs only its patchable-list token substituted.
    source = (ROOT / "shared" / "judge_lib.py").read_text(encoding="utf-8")
    source = source.replace("%%PATCHABLE_FILES%%", "[]")
    namespace = {"__file__": str(ROOT / "shared" / "judge_lib.py")}
    with patch.dict(sys.modules, {"torch": ModuleType("torch")}):
        exec(compile(source, namespace["__file__"], "exec"), namespace)

    score = namespace["score_from_checks"]
    base_result = namespace["base_result"]
    checks = {f"check_{i}": True for i in range(5)}
    checks["check_4"] = False
    partial = base_result()
    score(partial, checks, 5)
    assert partial["score"] == partial["raw_accuracy"] == 0.8
    assert partial["passed_checks"] == 4
    assert partial["metrics"]["trusted_score"] == 0.8
    assert partial["failure_mode"] == "underfit"
    assert partial["checks"]["check_4"] is False
    assert partial["checks"]["hidden_metric_passed"] is False
    assert partial["checks"]["anti_gaming_passed"] is True

    passed = base_result()
    score(passed, dict.fromkeys(checks, True), 5)
    assert passed["score"] == passed["raw_accuracy"] == 1.0
    assert passed["failure_mode"] == "pass"
    assert passed["checks"]["hidden_metric_passed"] is True

    missing_edit = base_result(_required_files_ok=False)
    score(missing_edit, dict.fromkeys(checks, True), 5)
    assert missing_edit["raw_accuracy"] == 1.0
    assert missing_edit["score"] == 0.95
    assert missing_edit["failure_mode"] == "overfit_visible_tests"
    assert missing_edit["checks"]["anti_gaming_passed"] is False
    misconfigured = base_result()
    score(misconfigured, dict.fromkeys(checks.keys() - {"check_4"}, True), 5)
    assert misconfigured["score"] == 0.0
    assert misconfigured["failure_mode"] == "judge_runtime_error"
    assert "expected 5 checks, got 4" in misconfigured["notes"][0]
    assert misconfigured["metrics"]["actual_total_checks"] == 4


def test_unknown_judge_failure_mode_is_unscored_even_if_score_says_pass(capsys):
    source = (ROOT / "shared" / "judge_lib.py").read_text(encoding="utf-8")
    source = source.replace("%%PATCHABLE_FILES%%", "[]")
    namespace = {"__file__": str(ROOT / "shared" / "judge_lib.py")}
    with patch.dict(sys.modules, {"torch": ModuleType("torch")}):
        exec(compile(source, namespace["__file__"], "exec"), namespace)
    result = namespace["base_result"](score=1.0)
    with pytest.raises(SystemExit) as exc:
        namespace["emit"](result)
    assert exc.value.code == 1
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["score"] == 0
    assert emitted["failure_mode"] == "judge_runtime_error"


def test_required_multifile_edit_is_non_terminal():
    """Missing required files should be recorded, not prevent partial scoring."""
    lib = (ROOT / "shared" / "judge_lib.py").read_text(encoding="utf-8")
    assert "def require_changed_files" in lib
    assert "This is intentionally not an immediate terminal failure" in lib
    body = lib.split("def require_changed_files", 1)[1]
    assert "emit(result)" not in body.split("def ", 1)[0]
