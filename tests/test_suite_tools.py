from __future__ import annotations

import json
from pathlib import Path

from tools.notebook_mode import detect_capabilities
from tools.run_suite import _build_command, run_suite
from tools.suite_inventory import build_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_audits_registry_and_representative_cases():
    manifest = build_manifest(root=ROOT, matrix="representative", seeds=[0])
    assert manifest["registry_audit"]["clean"] is True
    assert manifest["environment_count"] == manifest["registry_audit"]["registry_entry_count"]
    assert manifest["case_count"] == manifest["environment_count"]
    assert manifest["ready_for_scheduler"] is True
    assert all(case["runner"] == "arena_episode" for case in manifest["cases"])
    assert all(case["status"] == "planned" for case in manifest["cases"])


def test_inventory_all_matrix_expands_declared_vectors():
    manifest = build_manifest(root=ROOT, matrix="all", seeds=[0, 1])
    expected = sum(
        environment["difficulty_vector_count"] * 2
        for environment in manifest["environments"]
    )
    assert manifest["case_count"] == expected
    assert manifest["selection"]["matrix"] == "all"
    assert len({case["case_id"] for case in manifest["cases"]}) == expected


def test_scheduler_dry_run_checkpoints_and_writes_coverage(tmp_path):
    manifest = build_manifest(root=ROOT, matrix="representative", seeds=[0])
    manifest["cases"] = manifest["cases"][:2]
    manifest["case_count"] = len(manifest["cases"])
    output = tmp_path / "suite"
    checkpoint = run_suite(
        manifest,
        output_dir=output,
        provider="custom",
        model="offline/pinned",
        api_key_env="NOT_SET",
        api_base="https://example.invalid/v1",
        max_steps=1,
        max_tokens=7,
        invalid_retries=0,
        max_api_calls=1,
        dry_run=True,
    )
    assert checkpoint["paused"] is True
    assert checkpoint["pause_reason"] == "max_api_calls"
    assert len(checkpoint["results"]) == 1
    assert checkpoint["results"][0]["status"] == "planned"
    assert (output / "suite_checkpoint.json").is_file()
    coverage = json.loads((output / "coverage.json").read_text())
    assert coverage["counts"] == {"planned": 1}
    assert "conditional" not in coverage


def test_scheduler_command_contains_no_literal_secret():
    command = _build_command(
        {
            "environment": "glyph",
            "difficulty": "easy,easy,easy,easy,easy,easy",
            "seed": 0,
        },
        provider="custom",
        model="provider/model",
        api_key_env="SUITE_API_KEY",
        secrets=None,
        api_base="https://example.invalid/v1",
        sandbox="docker",
        output_dir=Path("runs/test"),
        max_steps=3,
        max_tokens=9,
        invalid_retries=1,
        keep_images=False,
        keep_workspace=False,
    )
    rendered = " ".join(command)
    assert "SUITE_API_KEY" in rendered
    assert "secret-value" not in rendered
    assert "--api-key " not in rendered


def test_notebook_capability_report_has_explicit_isolation_policy():
    capabilities = detect_capabilities(ROOT)
    assert "execution" in capabilities
    assert capabilities["execution"]["local_episode"] == "not_supported_by_default"
    assert capabilities["execution"]["trajectory_direct_answer"] == "host_controller_only"
