from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena.experiment_schema import ExperimentSpec, expand_counterfactual_twins  # noqa: E402
from tools.experiment_family import compile_family  # noqa: E402
from tools.run_suite import run_suite  # noqa: E402


def _spec(**overrides: object) -> ExperimentSpec:
    value = {
        "schema_version": 1,
        "id": "demo",
        "title": "Demo",
        "hypothesis": "Matched presentation twins preserve behavior.",
        "base_environment": "epistemic_games",
        "capability_requirements": ["infer", "test"],
        "difficulty_axes": ["scenario", "evidence"],
        "latent_factors": [
            {"id": "task", "role": "task_state", "description": "hidden task"},
            {"id": "mechanism", "role": "causal_mechanism", "description": "generator"},
            {"id": "observation", "role": "observable_state", "description": "transcript"},
            {"id": "evaluator", "role": "evaluator_state", "description": "judge"},
            {"id": "belief", "role": "agent_belief", "description": "reported belief"},
        ],
        "interventions": [
            {
                "id": "terminology",
                "kind": "terminology",
                "relation": "semantically_equivalent",
                "description": "rename terms",
            },
            {
                "id": "private_delivery",
                "kind": "epistemic_event",
                "relation": "epistemically_equivalent",
                "description": "change delivery scope",
            },
        ],
        "measurements": [
            {"id": "outcome", "metric": "outcome_score", "source": "outcome", "description": "outcome"},
            {"id": "switches", "metric": "hypothesis_switch_count", "source": "trajectory", "description": "switches"},
        ],
        "controls": ["same seed", "same task state"],
        "expected_invariances": ["terminology"],
        "expected_differences": ["private_delivery"],
        "observation_function": {"id": "obs", "description": "bounded observation"},
        "reward_proxy": {"id": "reward", "description": "terminal plus process"},
        "evaluator_policy": {"id": "judge", "description": "trajectory judge"},
    }
    value.update(overrides)
    return ExperimentSpec.from_dict(value)


def test_schema_rejects_duplicate_ids_and_missing_controls() -> None:
    with pytest.raises(ValueError, match="intervention ids must be unique"):
        _spec(interventions=[
            {"id": "same", "kind": "terminology", "description": "a"},
            {"id": "same", "kind": "evaluator", "description": "b"},
        ])
    with pytest.raises(ValueError, match="at least one control"):
        _spec(controls=[])


def test_digest_is_stable_and_policies_are_first_class() -> None:
    left = _spec()
    right = _spec()
    assert left.digest() == right.digest()
    assert left.as_dict()["observation_function"]["id"] == "obs"
    assert left.as_dict()["reward_proxy"]["id"] == "reward"
    assert left.as_dict()["evaluator_policy"]["id"] == "judge"


def test_twin_expansion_preserves_capability_and_marks_unmaterialized() -> None:
    spec = _spec()
    rows = expand_counterfactual_twins(
        spec,
        [{"case_id": "base-1", "environment": "epistemic_games", "difficulty": "fixed", "seed": 7}],
    )
    assert [row["variant_id"] for row in rows] == ["baseline", "terminology", "private_delivery"]
    assert all(row["environment"] == "epistemic_games" for row in rows)
    assert all(row["difficulty"] == "fixed" and row["seed"] == 7 for row in rows)
    assert all(row["capability_requirements"] == ["infer", "test"] for row in rows)
    assert all(row["difficulty_vector"] == "fixed" for row in rows)
    assert len({row["twin_group_id"] for row in rows}) == 1
    assert all(row["experiment_materialized"] is False for row in rows[1:])
    assert set(rows[0]["counterfactual_partner_ids"]) == {rows[1]["case_id"], rows[2]["case_id"]}


def test_example_compiles_without_provider_or_docker(tmp_path: Path) -> None:
    output = tmp_path / "family.json"
    result = compile_family(ROOT / "experiments" / "epistemic_invariance.yaml", output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert result["case_count"] == 5
    assert loaded["safety"]["provider_calls"] == 0
    assert loaded["safety"]["docker_started"] is False
    assert loaded["ready_for_scheduler"] is False
    assert len(loaded["cases"]) == 5
    with pytest.raises(ValueError, match="unmaterialized interventions"):
        run_suite(
            loaded,
            output_dir=tmp_path / "runs",
            provider="atria",
            model="model",
            api_key_env="UNUSED",
            allow_config_drift=True,
        )
