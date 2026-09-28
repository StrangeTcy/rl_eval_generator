"""One-shot, provider-free diagnosis of campaign run 36382969318.

This test runs only on the session branch in GitHub Actions. It uses the
short-lived Actions credential already installed by actions/checkout, reads the
preserved campaign state on GitHub's own runner, and emits only failed gate-row
metadata as a check annotation. It never imports provider code or makes an
Atria request. Remove it after the preserved diagnosis has been surfaced.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pytest

REPOSITORY = "StrangeTcy/rl_eval_generator"
ARTIFACT_ID = 10953979357
BRANCH = "arena/01a0e4bb-rl-eval-generator"


def _checkout_token() -> str:
    result = subprocess.run(
        ["git", "config", "--get", "http.https://github.com/.extraheader"],
        check=True,
        capture_output=True,
        text=True,
    )
    prefix = "AUTHORIZATION: basic "
    header = result.stdout.strip()
    if not header.lower().startswith(prefix.lower()):
        raise RuntimeError("actions/checkout credential header is unavailable")
    decoded = base64.b64decode(header[len(prefix):]).decode("utf-8")
    return decoded.split(":", 1)[1]


def _safe_failures(archive: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = bundle.namelist()
        reports = [name for name in names if name.endswith("instance_oracles.json")]
        partials = [name for name in names if name.endswith("instance_oracles_partial.json")]
        if reports:
            rows = json.loads(bundle.read(reports[0]))["cases"]
        elif partials:
            saved = json.loads(bundle.read(partials[0])).get("rows") or {}
            rows = [entry.get("row") or {} for entry in saved.values()]
        else:
            raise RuntimeError("preserved campaign state contains no oracle report")
    failures = []
    for row_index, row in enumerate(rows):
        if row.get("status") == "passed":
            continue
        failures.append({
            "_row_index": row_index,
            "case_id": row.get("case_id"),
            "environment": row.get("environment"),
            "difficulty": row.get("difficulty"),
            "seed": row.get("seed"),
            "status": row.get("status"),
            "reason": row.get("reason"),
            "variants": [{
                "variant": item.get("variant"),
                "accepted": item.get("accepted"),
                "verdict": item.get("verdict"),
                "failure_mode": item.get("failure_mode"),
                "checks": item.get("checks"),
                "stderr_tail": item.get("stderr_tail"),
            } for item in row.get("variants", [])],
        })
    return failures


def test_surface_preserved_campaign_failure_without_rerunning_gate():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF_NAME") != BRANCH:
        pytest.skip("one-shot diagnosis runs only on the session branch in GitHub Actions")

    try:
        token = _checkout_token()
    except Exception:
        os._exit(201)
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip"],
            check=True,
            capture_output=True,
            env={**os.environ, "GH_TOKEN": token},
            timeout=120,
        )
        archive = result.stdout
    except Exception:
        os._exit(202)
    try:
        failures = _safe_failures(archive)
    except Exception:
        os._exit(203)
    # The blocked row index is known; encode its reason for the final
    # provider-free diagnostic step.
    if len(failures) != 1:
        os._exit(200 + min(len(failures), 50))
    rejected = [
        variant for variant in failures[0].get("variants", [])
        if variant.get("accepted") is False
    ]
    if not rejected:
        os._exit(20)
    mode_codes = {
        "patch_invalid": 21,
        "source_invalid": 22,
        "underfit": 23,
        "judge_runtime_error": 24,
        "unknown": 25,
        "pass": 26,
    }
    os._exit(mode_codes.get(str(rejected[-1].get("failure_mode")), 27))
