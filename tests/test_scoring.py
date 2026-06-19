from pathlib import Path

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


def test_required_multifile_edit_is_non_terminal():
    """Missing required files should be recorded, not prevent partial scoring."""
    lib = (ROOT / "shared" / "judge_lib.py").read_text(encoding="utf-8")
    assert "def require_changed_files" in lib
    assert "This is intentionally not an immediate terminal failure" in lib
    body = lib.split("def require_changed_files", 1)[1]
    assert "emit(result)" not in body.split("def ", 1)[0]
