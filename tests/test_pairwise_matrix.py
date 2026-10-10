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


# --------------------------------------------------------------------------
# interventions in a paid campaign: only what a twin check can defend
# --------------------------------------------------------------------------

from tools.twin_preflight import intervention_groups, verify_manifest_twins  # noqa: E402


def _manifest(cases: list[dict]) -> dict:
    return {"cases": cases, "case_count": len(cases), "selection": {"matrix": "pairwise"}}


def _case(case_id: str, env: str, iid: str | None, seed: int = 0, **extra: str) -> dict:
    levels = extra.pop("difficulty_levels", {"a": "easy", "b": "easy"})
    case = {
        "case_id": case_id,
        "environment": env,
        "difficulty": ",".join(levels.values()),
        "difficulty_levels": levels,
        "seed": seed,
    }
    if iid is not None:
        case["interventions"] = iid
        case["baseline_case_id"] = case_id.replace(f"__{iid}__", "__")
    case.update(extra)
    return case


def test_intervention_groups_collapses_twins_sharing_a_base_instance() -> None:
    manifest = _manifest([
        _case("moco__a-easy_b-easy__terminology__seed-0", "moco", "terminology"),
        _case("moco__a-easy_b-easy__visible_proxy__seed-0", "moco", "visible_proxy"),
        _case("moco__a-easy_b-hard__terminology__seed-0", "moco", "terminology",
              difficulty_levels={"a": "easy", "b": "hard"}),
        _case("glyph__a-easy_b-easy__seed-0", "glyph", None),
    ])
    groups = intervention_groups(manifest)
    assert len(groups) == 2, "twins sharing a base instance are one family call"
    (key, members), = [item for item in groups.items() if item[0][0] == "moco" and item[0][1] == "easy,easy"]
    assert sorted(members) == ["terminology", "visible_proxy"]
    assert key == ("moco", "easy,easy", 0)


def test_twin_preflight_does_nothing_when_there_is_nothing_to_verify(tmp_path: Path) -> None:
    off = verify_manifest_twins(_manifest([_case("glyph__a-easy_b-easy__seed-0", "glyph", None)]), mode="off")
    assert off["status"] == "skipped" and off["group_count"] == 0
    empty = verify_manifest_twins(_manifest([]), mode="advisory", out_path=tmp_path / "r.json")
    assert empty["status"] == "not_applicable"
    assert (tmp_path / "r.json").exists()


def test_twin_preflight_reports_verdicts_per_billed_case(tmp_path: Path) -> None:
    """One real family.py run: the report must key verdicts by the campaign's own
    case ids, and strict must refuse to let an unverified twin be billed."""
    built = atria_campaign.build_manifest(root=ROOT, matrix="covering", seeds=[0], expand_interventions=True)
    twin = next(case for case in built["cases"] if str(case["environment"]) == "glyph" and case.get("interventions"))
    report = verify_manifest_twins(_manifest([twin]), out_path=tmp_path / "twin.json", mode="advisory")
    assert report["group_count"] == 1 and report["case_count"] == 1
    record = report["cases"][str(twin["case_id"])]
    assert record["twin_check"] in {"pass", "fail", "unverified"}, record
    assert record["family_exit_code"] in {0, 1}
    assert report["status"] in {"passed", "unverified"}
    if record["twin_check"] != "pass":
        with pytest.raises(ValueError, match="did not verify"):
            verify_manifest_twins(_manifest([twin]), mode="strict")


def test_pairwise_manifest_expands_interventions_only_where_declared() -> None:
    plain = atria_campaign.build_manifest(root=ROOT, matrix="pairwise", seeds=[0])
    expanded = atria_campaign.build_manifest(root=ROOT, matrix="pairwise", seeds=[0], expand_interventions=True)
    assert expanded["case_count"] == len(expanded["cases"]) > plain["case_count"]
    twins = [case for case in expanded["cases"] if case.get("interventions")]
    assert {str(case["environment"]) for case in twins} <= {
        "glyph", "moco", "css_state_machine", "epistemic_games"
    }
    ids = {str(case["case_id"]) for case in expanded["cases"]}
    missing = [case["case_id"] for case in twins if case.get("baseline_case_id") not in ids]
    assert not missing, f"twins billed without their base: {missing[:3]}"


def _profile_with(**matrix: object) -> dict:
    profile = yaml.safe_load((ROOT / "experiments/mercury_covering_campaign.yaml").read_text())
    settings = {"mode": "pairwise", "seeds": [0]}
    settings.update(matrix)
    profile["matrix"] = settings
    return profile


def test_twin_verification_policy_defaults_and_refusals() -> None:
    assert atria_campaign.twin_verification_of({}) == "off"
    assert atria_campaign.twin_verification_of({"matrix": {"interventions": True}}) == "advisory"
    assert atria_campaign.matrix_interventions_of({"matrix": {"interventions": False}}) is False
    for mode in ("strict", "advisory", "bill_verified_only"):
        atria_campaign._validate_campaign_profile(_profile_with(interventions=True, twin_verification=mode))
    atria_campaign._validate_campaign_profile(_profile_with(interventions=False, twin_verification="off"))
    # disabling verification while billing intervention cases is the one thing
    # that would let an inert overlay be read as model-level invariance.
    with pytest.raises(ValueError, match="cannot disable twin verification"):
        atria_campaign._validate_campaign_profile(_profile_with(interventions=True, twin_verification="off"))
    with pytest.raises(ValueError, match="twin_verification must be"):
        atria_campaign._validate_campaign_profile(_profile_with(interventions=True, twin_verification="yolo"))
    with pytest.raises(ValueError, match="must be a boolean"):
        atria_campaign._validate_campaign_profile(_profile_with(interventions="yes"))


def test_comprehensive_profiles_are_valid_and_priced_against_their_own_matrix() -> None:
    for name in ("mercury", "reasoning_atria"):
        profile = yaml.safe_load((ROOT / f"experiments/{name}_pairwise_campaign.yaml").read_text())
        atria_campaign._validate_campaign_profile(profile)
        assert profile["name"] == f"{name}_pairwise_campaign"
        assert profile["matrix"]["mode"] == "pairwise"
        assert profile["matrix"]["interventions"] is True
        assert profile["matrix"]["twin_verification"] == "bill_verified_only"
        manifest = atria_campaign.build_manifest(
            root=ROOT,
            matrix=atria_campaign.matrix_mode_of(profile),
            seeds=[0],
            expand_interventions=atria_campaign.matrix_interventions_of(profile),
        )
        assert manifest["case_count"] == 496
        assert profile["limits"]["max_api_calls"] >= manifest["case_count"] * 40
        assert profile["limits"]["max_tokens_total"] > 0


def test_pairwise_workflows_are_self_consistent_and_cannot_crosstalk() -> None:
    """A second campaign on the same repo must not inherit the first one's Issue,
    state directory, artifact prefix or profile - that similarity made two live
    runs indistinguishable once, so it is asserted rather than eyeballed."""
    for slug, profile_stem, label in (
        ("mercury", "mercury_pairwise", "Mercury pairwise campaign"),
        ("reasoning-atria", "reasoning_atria_pairwise", "pairwise campaign"),
    ):
        handoff = (ROOT / f"handoff/{slug}-pairwise-campaign.yml").read_text()
        example = (ROOT / f"docs/workflows/{slug}-pairwise-campaign.yml.example").read_text()
        assert handoff == example, f"{slug}: handoff copy and docs example drifted"
        assert label in handoff
        assert f"experiments/{profile_stem}_campaign.yaml" in handoff
        assert f"runs/{profile_stem}_campaign" in handoff
        assert f"{profile_stem}_status_issue.txt" in handoff
        assert f"-{slug}-pairwise-state-" in handoff or "pairwise-state-" in handoff
        for stale in ("_covering_status_issue.txt", "runs/mercury_covering_campaign", "runs/reasoning_atria_covering_campaign"):
            assert stale not in handoff, f"{slug}: still points at the covering campaign's {stale}"
        assert 'timeout-minutes: 330' in handoff and "timeout-minutes: 350" in handoff
        assert "CAMPAIGN_SECONDS=$((19800 - ELAPSED_SECONDS - 60))" in handoff
        assert "test -f tools/twin_preflight.py" in handoff, "launcher must refuse code without the twin preflight"
