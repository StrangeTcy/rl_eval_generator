"""Provider-free checks of generated judge code, not just template syntax."""
from __future__ import annotations

import contextlib
import io
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import env_runner
from tools.atria_first_experiment import PROFILE_DEFAULT, _validate_profile
from tools.first_experiment import _generation_preflight, _select_manifest
from tools.judge_preflight import validate_generated_judge
from tools.suite_inventory import _preflight_case

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))[
    "environments"
]


def _levels(env: str) -> dict[str, str]:
    config = yaml.safe_load((ROOT / REGISTRY[env]).read_text(encoding="utf-8"))
    return {axis["id"]: next(iter(axis["levels"])) for axis in config["axes"]}


@pytest.mark.parametrize("env", sorted(REGISTRY))
def test_each_registered_judge_and_its_deferred_scripts_preflight(env: str):
    case = {"environment": env, "difficulty_levels": _levels(env), "seed": 0}
    report = _preflight_case(case, ROOT)
    assert report["status"] == "ready", f"{env}: {report}"


def test_exact_atria_pilot_vectors_preflight_before_compatibility():
    manifest = _select_manifest(_validate_profile(PROFILE_DEFAULT), PROFILE_DEFAULT)
    reports = _generation_preflight(manifest)
    assert len(reports) == 5
    assert all(report["status"] == "ready" for report in reports), reports


def test_judge_preflight_rejects_missing_globals_in_both_processes(tmp_path):
    judge = tmp_path / "judge.py"
    judge.write_text("def score():\n    return json.loads('{}')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="undefined global name\\(s\\): json"):
        validate_generated_judge(judge)

    judge.write_text(
        'def main(workdir):\n'
        '    eval_script = workdir + "/_eval_runner.py"\n'
        '    with open(eval_script, "w") as f:\n'
        '        f.write("print(os.getcwd())\\n")\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="undefined global name\\(s\\): os"):
        validate_generated_judge(judge)


def test_judge_preflight_rejects_accidental_outer_fstring_interpolation(tmp_path):
    judge = tmp_path / "judge.py"
    judge.write_text(
        'def main(workdir):\n'
        '    eval_script = workdir + "/_eval_runner.py"\n'
        '    with open(eval_script, "w") as f:\n'
        '        f.write(f\'# {"route_A": 90}\\n\')\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="may interpolate only the judge workdir"):
        validate_generated_judge(judge)


def _run_real_local_judge(
    env: str, model_file: str, solution: str, tmp_path: Path, monkeypatch
) -> dict:
    """Exercise patch validation, the generated judge, and its child process.

    These judges do not use torch; a temporary import shim avoids installing
    the ML stack in the host test runner. Docker still installs real torch.
    """
    if shutil.which("patch") is None:
        pytest.skip("patch executable is required for local judge integration")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")
    episode_id = f"judge_smoke_{env}_{uuid.uuid4().hex[:8]}"
    args = SimpleNamespace(
        episode_id=episode_id,
        env=env,
        difficulty="easy,easy",
        seed=0,
        max_steps=5,
        sandbox="local",
        keep_images=False,
        keep_workspace=True,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        env_runner.reset(args)
    state = env_runner._load_state(episode_id)
    (Path(state["env_dir"]) / "judge" / "torch.py").write_text(
        "# Host test shim: only the import is required for this judge.\n", encoding="utf-8"
    )
    (Path(state["workspace"]) / model_file).write_text(solution, encoding="utf-8")
    _observation, score, done, info = env_runner._submit(state, {"confirm": True})
    assert done and "judge_result" in info, info
    assert score == 1.0, info["judge_result"]
    return info["judge_result"]


def test_regex_judge_grades_correct_regex_solution(tmp_path, monkeypatch):
    result = _run_real_local_judge(
        "regex_state_machine",
        "regex_machine.py",
        """import re

RULE = {"111": "0", "110": "1", "101": "1", "100": "0",
        "011": "1", "010": "1", "001": "1", "000": "0"}

class RegexAutomaton:
    def step(self, state_str):
        padded = "0" + state_str + "0"
        return "".join(RULE[m.group(1)] for m in re.finditer(r"(?=([01]{3}))", padded))
""",
        tmp_path,
        monkeypatch,
    )
    assert result["verdict"] == "PASS"
    assert all(result["checks"][check] for check in
               ("regex_used", "basic_step", "length_preservation", "randomized_accuracy"))


def test_sql_judge_renders_child_and_grades_correct_query(tmp_path, monkeypatch):
    result = _run_real_local_judge(
        "sql_fixed_point",
        "query_module.py",
        """class SQLReachabilityEngine:
    def get_reachability_query(self):
        return '''
            WITH RECURSIVE reach(start, target) AS (
                SELECT src, dst FROM edges
                UNION
                SELECT reach.start, edges.dst
                FROM reach JOIN edges ON reach.target = edges.src
            )
            SELECT q.start, q.target FROM queries AS q
            JOIN reach ON q.start = reach.start AND q.target = reach.target
        '''
""",
        tmp_path,
        monkeypatch,
    )
    assert result["verdict"] == "PASS"
    assert all(result["checks"][check] for check in
               ("query_is_sql", "cycle_handling", "reflexive_semantics", "randomized_reachability"))
