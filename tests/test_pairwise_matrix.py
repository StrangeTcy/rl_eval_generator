"""The strength-2 matrix mode: what it must cover, and what it must not break.

``covering`` varies one axis at a time, so no two-axis interaction is observable
in it at all.  ``pairwise`` is the cheapest design that can show one, and it is
the mode the campaign profile may now select - which drags two fail-closed
campaign preflights along with it, and both are asserted here.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import atria_campaign
from tools.suite_inventory import _difficulty_vectors


def _axes(levels: list[list[str]]) -> list[dict]:
    return [
        {"id": f"axis{i}", "description": "", "levels": sorted(set(lv))}
        for i, lv in enumerate(levels)
    ]


def _pairs(vectors: list[dict[str, str]]) -> set[tuple[str, str, str, str]]:
    out = set()
    for vector in vectors:
        items = sorted(vector.items())
        for (k1, v1), (k2, v2) in itertools.combinations(items, 2):
            out.add((k1, v1, k2, v2))
    return out


def test_pairwise_covers_every_level_pair_of_every_axis_pair() -> None:
    axes = _axes([["easy", "hard", "medium"], ["a", "b"], ["x", "y", "z"]])
    vectors = _difficulty_vectors(axes, "pairwise", None)
    full = [
        dict(zip([axis["id"] for axis in axes], combo, strict=True))
        for combo in itertools.product(*[axis["levels"] for axis in axes])
    ]
    assert _pairs(vectors) == _pairs(full), "every level pair of every axis pair must appear"
    assert len(vectors) < len(full), "and not by brute force"


def test_pairwise_includes_the_uniform_difficulty_ladder() -> None:
    axes = _axes([["easy", "hard", "medium"]] * 4)
    vectors = _difficulty_vectors(axes, "pairwise", None)
    for level in ("easy", "medium", "hard"):
        assert {a["id"]: level for a in axes} in vectors, f"all-{level} row missing"


def test_pairwise_is_deterministic_and_inside_the_full_product() -> None:
    axes = _axes([["easy", "hard", "medium"], ["one", "two"], ["p", "q", "r"], ["easy", "hard"]])
    first = _difficulty_vectors(axes, "pairwise", None)
    second = _difficulty_vectors(axes, "pairwise", None)
    assert first == second
    space = {
        tuple(sorted(dict(zip([axis["id"] for axis in axes], combo, strict=True)).items()))
        for combo in itertools.product(*[axis["levels"] for axis in axes])
    }
    selected = {tuple(sorted(vector.items())) for vector in first}
    assert selected <= space, "pairwise must only emit vectors the full product contains"
    assert len(selected) == len(first), "no duplicate vectors"


def test_covering_varies_one_axis_and_pairwise_does_not() -> None:
    """The reason the mode exists: t=1 cannot see an interaction, t=2 must."""

    def moved_axes(vector: dict[str, str], base: dict[str, str]) -> int:
        return sum(1 for key in base if vector[key] != base[key])

    axes = _axes([["easy", "hard", "medium"]] * 5)
    base = {a["id"]: "easy" for a in axes}
    covering = _difficulty_vectors(axes, "covering", None)
    assert max(moved_axes(v, base) for v in covering) == 1
    pairwise = _difficulty_vectors(axes, "pairwise", None)
    assert max(moved_axes(v, base) for v in pairwise) >= 2
    assert len(pairwise) < len(_difficulty_vectors(axes, "all", None))
    assert _pairs(_difficulty_vectors(axes, "all", None)) <= _pairs(pairwise)


def test_pairwise_over_the_registry_ensures_every_level_and_stays_small() -> None:
    covering = atria_campaign.build_manifest(root=ROOT, matrix="covering", seeds=[0])
    pairwise = atria_campaign.build_manifest(root=ROOT, matrix="pairwise", seeds=[0])
    def levels(manifest: dict) -> set[tuple[str, str, str]]:
        return {
            (str(case["environment"]), str(axis), str(level))
            for case in manifest["cases"]
            for axis, level in (case.get("difficulty_levels") or {}).items()
        }

    assert levels(covering) <= levels(pairwise), "pairwise must not lose a level covering served"
    assert pairwise["case_count"] == len({case["case_id"] for case in pairwise["cases"]})
    assert pairwise["case_count"] < covering["case_count"] * 2


def _profile() -> dict:
    profile = yaml.safe_load((ROOT / "experiments/mercury_covering_campaign.yaml").read_text())
    profile["matrix"] = {"mode": "pairwise", "seeds": [0]}
    return profile


def test_profile_validation_accepts_pairwise_and_still_rejects_other_modes() -> None:
    profile = _profile()
    atria_campaign._validate_campaign_profile(profile)
    assert atria_campaign.matrix_mode_of(profile) == "pairwise"
    assert atria_campaign.matrix_mode_of({"matrix": {"mode": "covering"}}) == "covering"
    assert atria_campaign.matrix_mode_of({}) == "covering", "default must keep existing profiles resumable"
    for mode in ("all", "representative", "quads"):
        bad = _profile()
        bad["matrix"]["mode"] = mode
        with pytest.raises(ValueError, match="matrix.mode"):
            atria_campaign._validate_campaign_profile(bad)
    with pytest.raises(ValueError, match="unknown matrix"):
        _difficulty_vectors(_axes([["easy", "hard"]]), "quads", None)


def test_gate_blocked_exclusions_survive_a_matrix_mode_switch(tmp_path: Path) -> None:
    """Pairwise does not generate covering's single-axis spikes, and the reviewed
    exclusion list is written in those spikes.  Absent-but-not-drifted ids are
    recorded; they must not kill the campaign at startup."""
    profile = _profile()
    manifest = atria_campaign.build_manifest(root=ROOT, matrix="pairwise", seeds=[0])
    atria_campaign._apply_gate_blocked_exclusions(manifest, profile)
    record = manifest["manual_gate_blocked_exclusions_not_enumerated"]
    assert record["count"] == len(profile["manual_gate_blocked_exclusions"]["cases"])
    assert manifest["known_gate_blocked_omissions"]["omitted_case_count"] == 0
    assert manifest["case_count"] == len(manifest["cases"])


def test_covering_exclusions_still_apply_verbatim() -> None:
    profile = _profile()
    manifest = atria_campaign.build_manifest(root=ROOT, matrix="covering", seeds=[0])
    before = manifest["case_count"]
    atria_campaign._apply_gate_blocked_exclusions(manifest, profile)
    assert manifest["case_count"] == before - len(profile["manual_gate_blocked_exclusions"]["cases"])
    assert "manual_gate_blocked_exclusions_not_enumerated" not in manifest


def test_typo_in_exclusion_list_still_fails_closed() -> None:
    profile = _profile()
    profile["manual_gate_blocked_exclusions"] = {
        "cases": [{"case_id": "no_such_env__axis=easy__seed-0", "calibration_class": "x"}]
    }
    manifest = atria_campaign.build_manifest(root=ROOT, matrix="pairwise", seeds=[0])
    with pytest.raises(ValueError, match="absent from manifest"):
        atria_campaign._apply_gate_blocked_exclusions(manifest, profile)


def test_paid_pairwise_run_requires_an_explicit_ceiling() -> None:
    source = (ROOT / "tools/run_suite.py").read_text()
    assert 'matrix in {"all", "covering", "pairwise"}' in source
