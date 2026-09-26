#!/usr/bin/env python3
"""Provider-free, fail-closed behavioral gate for *exact generated instances*.

For a manifest case, generate once and submit independent patches to its real
local judge using env_runner's production patch/submission path: an empty no-op,
a syntactically valid but behaviorally wrong attempt, a reference repair, and —
for environments whose judges guard against visible-output hard-coding — a
"transcription" patch that hard-codes exactly what visible_tests.py asserts and
must still FAIL. Reference implementations live here, never in the agent
workspace. A reference is intentionally *not* inferred for unimplemented
environments; those cases remain blocked, not compile-only "verified".

This is an offline host integration test, not a Docker-isolation proof, an agent
trajectory, or a guarantee that the reference generalizes to other vectors.
Slow ML environments (notably Glyph) are opt-in for standalone inspection, but
live suite/first-five callers must run them before any paid request.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402
from tools.public_bayes_oracle import solve_task_md  # noqa: E402


def _replace(workspace: Path, name: str, old: str, new: str) -> None:
    path = workspace / name
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise ValueError(f"{name}: expected exactly one occurrence of {old!r}; reference is not configured for this vector")
    path.write_text(source.replace(old, new), encoding="utf-8")


def _write(workspace: Path, name: str, source: str) -> None:
    (workspace / name).write_text(source, encoding="utf-8")


def _class_name(workspace: Path, name: str) -> str:
    tree = ast.parse((workspace / name).read_text(encoding="utf-8"))
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError(f"{name}: expected one generated class, found {classes}")
    return classes[0]


def _state_carry(workspace: Path, *, wrong: bool) -> None:
    _replace(workspace, "recurrent_block.py", "state = self.transition(x)",
             "state = self.transition(x + state * 0.0)" if wrong else "state = self.transition(state)")


def _rope(workspace: Path, *, wrong: bool) -> None:
    _replace(workspace, "rope.py", "torch.arange(seq_len, device=device)",
             "torch.arange(offset, offset + seq_len, device=device)")
    if not wrong:
        _replace(workspace, "rope.py", "return torch.cat((-x2, x1), dim=-1)",
                 "return torch.stack((-x[..., 1::2], x[..., 0::2]), dim=-1).flatten(-2)")
    _replace(workspace, "attention.py", "offset = 0", "offset = cache.position_offset()")
    _replace(workspace, "cache.py", "return 0", "return self.tokens_seen")
    _replace(workspace, "cache.py", "self.tokens_seen = self.tokens_seen",
             "self.tokens_seen += int(chunk_len)")


def _moco(workspace: Path, *, wrong: bool) -> None:
    _replace(workspace, "moco_model.py", "logits = torch.cat([l_pos, l_neg], dim=1)",
             "logits = torch.cat([l_pos, l_neg], dim=1) / 1.0" if wrong
             else "logits = torch.cat([l_pos, l_neg], dim=1) / self.tau")
    _replace(workspace, "queue_ops.py", "queue[:, start:start + n] = keys.T",
             "queue[:, (torch.arange(n) + start) % k] = keys.T")


def _glyph(workspace: Path, *, wrong: bool) -> None:
    _replace(workspace, "model.py", "nn.MaxPool2d(2),\n        )",
             "nn.MaxPool2d(2),\n            nn.Conv2d(64, 128, kernel_size=3, padding=1),\n"
             "            nn.ReLU(),\n        )")
    model = workspace / "model.py"
    source = model.read_text(encoding="utf-8")
    start = source.index("self.classifier = nn.Sequential(")
    end = source.index("\n\n    def forward", start)
    classifier = (
        "self.classifier = nn.Sequential(\n"
        "            nn.AdaptiveAvgPool2d((1, 1)),\n"
        "            nn.Flatten(),\n"
        "            nn.Linear(128, 128),\n"
        "            nn.ReLU(),\n"
        "            nn.Linear(128, num_classes)\n"
        "        )"
    )
    model.write_text(source[:start] + classifier + source[end:], encoding="utf-8")
    _replace(workspace, "train.py", "optimizer = optim.SGD(model.parameters(), lr=1e-5)",
             "optimizer = optim.SGD(model.parameters(), lr=1e-4)" if wrong
             else "optimizer = optim.Adam(model.parameters(), lr=1e-3)")
    if not wrong:
        _replace(workspace, "train.py", "EPOCHS = 10", "EPOCHS = 18\ntorch.manual_seed(0)")


def _epistemic(workspace: Path, *, wrong: bool) -> None:
    solved = solve_task_md((workspace / "task.md").read_text(encoding="utf-8"))
    posterior = float(solved["posterior_world1"])
    # Wrong but valid answer data: opposite posterior, or deliberately strong
    # evidence if the true posterior is exactly 0.5.
    incorrect = 0.9 if abs(posterior - 0.5) < 1e-6 else 1.0 - posterior
    answer = {
        "posterior_world1": incorrect if wrong else posterior,
        "verdict": "distinguishable" if wrong else solved["verdict"],
        "most_supported": (
            "world1" if incorrect > 0.5 else "world2" if incorrect < 0.5 else "neither"
        ) if wrong else solved["most_supported"],
        "justification": "Posterior from the stated likelihoods and prior.",
    }
    old = (
        'ANSWER = {\n    "posterior_world1": None,\n    "verdict": None,\n'
        '    "most_supported": None,\n    "justification": None,\n}\n'
    )
    _replace(workspace, "answer.py", old, "ANSWER = " + repr(answer) + "\n")


def _regex(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "regex_machine.py")
    rule_110 = '{"111": "0", "110": "1", "101": "1", "100": "0",\n        "011": "1", "010": "1", "001": "1", "000": "0"}'
    if wrong:
        rule_110 = rule_110.replace('"110": "1"', '"110": "0"')
    _write(workspace, "regex_machine.py", f'''import re

RULE = {rule_110}

class {name}:
    def step(self, state_str):
        padded = "0" + state_str + "0"
        return "".join(RULE[m.group(1)] for m in re.finditer(r"(?=([01]{{3}}))", padded))
''')


def _sql(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "query_module.py")
    query = (
        "SELECT DISTINCT q.start, q.target FROM queries AS q "
        "JOIN edges AS e ON q.start = e.src AND q.target = e.dst"
        if wrong else
        "WITH RECURSIVE reach(start, target) AS ( "
        "SELECT src, dst FROM edges UNION "
        "SELECT reach.start, edges.dst FROM reach JOIN edges ON reach.target = edges.src "
        ") SELECT q.start, q.target FROM queries AS q "
        "JOIN reach ON q.start = reach.start AND q.target = reach.target"
    )
    _write(workspace, "query_module.py",
           f"class {name}:\n    def get_reachability_query(self):\n        return {query!r}\n")


def _css(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "css_logic.py")
    _write(workspace, "css_logic.py", f'''class {name}:
    def generate_parity_rules(self, n):
        rules = []
        for mask in range(1 << n):
            conditions = [f"#c{{i}}:checked" if mask & (1 << i)
                          else f"#c{{i}}:not(:checked)" for i in range(n)]
            parity = (mask.bit_count() + {1 if wrong else 0}) % 2
            target = "#out_odd" if parity else "#out_even"
            rules.append((" ~ ".join(conditions + [target]), {{"display": "block"}}))
        return rules
''')


def _lenses(workspace: Path, *, wrong: bool) -> None:
    _replace(workspace, "lenses.py", "return (a, 0.0)",
             "return (a, s[0])" if wrong else "return (a, s[1])")


def _spreadsheet(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "sheet_model.py")
    # Wrong-but-plausible recurrence drops the MIN: B_i = A_i + B_{i-1}.
    recurrence = "=A{i}+B{i-1}" if wrong else "=A{i}+MIN(B{i-1},B{i-2})"
    _write(workspace, "sheet_model.py", f'''class {name}:
    def build_dp_formulas(self, n):
        formulas = {{"B1": "=A1"}}
        if n >= 2:
            formulas["B2"] = "=A2+B1"
        for i in range(3, n + 1):
            formulas[f"B{{i}}"] = f"{recurrence}"
        return formulas
''')


def _template(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "template_machine.py")
    # Wrong-but-plausible template ignores the skip flag entirely.
    template = (
        "{% for op in operations %}{{ op.symbol * op.repeat }}{% endfor %}" if wrong else
        "{% for op in operations %}{% if not op.skip %}{{ op.symbol * op.repeat }}{% endif %}{% endfor %}"
    )
    _write(workspace, "template_machine.py", f'''class {name}:
    def get_template(self):
        return {template!r}
''')


def _ci(workspace: Path, *, wrong: bool) -> None:
    name = _class_name(workspace, "ci_machine.py")
    if wrong:
        # Plausible: layer = number of direct dependencies. Correct for the
        # basic two-job case, wrong for any chain longer than two hops.
        _write(workspace, "ci_machine.py", f'''class {name}:
    def generate_workflow(self, dependencies):
        wf = {{}}
        for job_id, parents in dependencies.items():
            wf[f"job_{{job_id}}"] = {{
                "needs": [f"job_{{p}}" for p in parents],
                "env": {{"LAYER": len(parents)}},
            }}
        return wf
''')
    else:
        _write(workspace, "ci_machine.py", f'''class {name}:
    def generate_workflow(self, dependencies):
        wf = {{}}
        remaining = list(dependencies)
        while remaining:
            progressed = False
            for job_id in list(remaining):
                parents = dependencies[job_id]
                if all(f"job_{{p}}" in wf for p in parents):
                    layer = max([wf[f"job_{{p}}"]["env"]["LAYER"] for p in parents], default=-1) + 1
                    wf[f"job_{{job_id}}"] = {{
                        "needs": [f"job_{{p}}" for p in parents],
                        "env": {{"LAYER": layer}},
                    }}
                    remaining.remove(job_id)
                    progressed = True
            if not progressed:
                raise ValueError("dependency cycle")
        return wf
''')


# A "transcription" patch hard-codes exactly what visible_tests.py asserts and
# gives up on everything else. Each one deliberately passes the agent-visible
# test; only the judge's held-out randomized checks can reject it.
def _regex_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "regex_machine.py")
    _write(workspace, "regex_machine.py", f'''import re

# Hard-codes the two transitions asserted by visible_tests.py.
_VISIBLE = {{"1": "1", "001": "011"}}

class {name}:
    def step(self, state_str):
        return re.sub(r"[01]+", lambda m: _VISIBLE.get(m.group(0), m.group(0)), state_str)
''')


def _sql_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "query_module.py")
    _write(workspace, "query_module.py", f'''class {name}:
    def get_reachability_query(self):
        # Literal reachable pairs from the visible_tests.py example graph.
        return ("SELECT 1 AS start, 2 AS target "
                "UNION ALL SELECT 1 AS start, 3 AS target")
''')


def _css_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "css_logic.py")
    _write(workspace, "css_logic.py", f'''class {name}:
    def generate_parity_rules(self, n):
        # Only the two n=2 configurations asserted by visible_tests.py.
        return [
            ("#c0:not(:checked) ~ #c1:not(:checked) ~ #out_even", {{"display": "block"}}),
            ("#c0:checked ~ #c1:not(:checked) ~ #out_odd", {{"display": "block"}}),
        ]
''')


def _spreadsheet_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "sheet_model.py")
    _write(workspace, "sheet_model.py", f'''class {name}:
    def build_dp_formulas(self, n):
        # Literal B-column values from the visible_tests.py example inputs.
        literal = {{"B1": "=10.0", "B2": "=15.0", "B3": "=12.0", "B4": "=20.0"}}
        return {{f"B{{i}}": literal.get(f"B{{i}}", "=0.0") for i in range(1, n + 1)}}
''')


def _template_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "template_machine.py")
    source = (
        "class " + name + ":\n"
        "    def get_template(self):\n"
        "        # Renders only the exact operation list asserted by visible_tests.py.\n"
        "        return '{% if operations == [{\"symbol\": \"A\", \"repeat\": 3, \"skip\": False},"
        " {\"symbol\": \"X\", \"repeat\": 5, \"skip\": True},"
        " {\"symbol\": \"B\", \"repeat\": 2, \"skip\": False}] %}AAABB{% endif %}'\n"
    )
    _write(workspace, "template_machine.py", source)


def _ci_transcription(workspace: Path) -> None:
    name = _class_name(workspace, "ci_machine.py")
    _write(workspace, "ci_machine.py", f'''class {name}:
    def generate_workflow(self, dependencies):
        # The exact diamond workflow verified by visible_tests.py, ignoring
        # the requested dependencies.
        return {{
            "job_1": {{"needs": [], "env": {{"LAYER": 0}}}},
            "job_2": {{"needs": ["job_1"], "env": {{"LAYER": 1}}}},
            "job_3": {{"needs": ["job_1"], "env": {{"LAYER": 1}}}},
            "job_4": {{"needs": ["job_2", "job_3"], "env": {{"LAYER": 2}}}},
        }}
''')

# Negative checks target the named behavior, not just patch format/required files.
# A third element adds the transcription variant: a patch that hard-codes the
# visible-test outputs must still FAIL the judge's randomized held-out checks.
REFERENCES: dict[str, tuple[Callable[..., None], str] | tuple[Callable[..., None], str, Callable[..., None]]] = {
    "rd_state_carry": (_state_carry, "hidden_depth_exact"),
    "rope": (_rope, "rope_pairing"),
    "moco": (_moco, "temperature_sensitive"),
    "glyph": (_glyph, "optimization_progressed"),
    "epistemic_games": (_epistemic, "posterior_within_strict_tolerance"),
    "regex_state_machine": (_regex, "randomized_accuracy", _regex_transcription),
    "sql_fixed_point": (_sql, "randomized_reachability", _sql_transcription),
    "css_state_machine": (_css, "parity_correctness", _css_transcription),
    "categorical_lenses": (_lenses, "get_put"),
    "spreadsheet_dataflow": (_spreadsheet, "randomized_invariance", _spreadsheet_transcription),
    "template_interpreter": (_template, "randomized_rendering", _template_transcription),
    "ci_dependency_graph": (_ci, "randomized_scheduling", _ci_transcription),
}


def _instance_hash(state: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for directory in (Path(state["original_workspace"]), Path(state["env_dir"]) / "judge"):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(directory)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def verify_reset_matches_oracle(
    oracle: dict[str, Any], episode_dir: Path, environment: str, difficulty: str, seed: int
) -> str:
    """Fail closed unless the agent's *actual* reset is byte-identical to the oracle.

    Generating twice from the same seed is not by itself sufficient evidence
    for a procedural task: templates, randomness, or code can drift between
    the reference run and the episode reset. Compare the untouched workspace
    and judge before the first provider action, not just their vector labels.
    """
    expected = oracle.get("instance_sha256")
    if oracle.get("status") != "passed" or not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Exact-instance oracle has no successful, fingerprinted reference")
    state_path = episode_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if (state.get("env"), state.get("difficulty"), state.get("seed")) != (
        environment, difficulty, seed
    ):
        raise ValueError("Reset instance vector/seed differs from the oracle case")
    actual = _instance_hash(state)
    if actual != expected:
        raise ValueError("Agent-visible reset differs from the reference-graded generated instance")
    return actual


def _run_variant(state: dict[str, Any], label: str, *, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    _observation, _score, done, info = env_runner._submit(state, {"confirm": True}, judge_timeout=timeout)
    result = info.get("judge_result", {})
    patch = Path(state["episode_dir"]) / "submission.patch"
    return {
        "variant": label, "done": done,
        "score": result.get("score"), "raw_accuracy": result.get("raw_accuracy"),
        "verdict": result.get("verdict"), "failure_mode": result.get("failure_mode"),
        "checks": result.get("checks", {}),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch.exists() else None,
        "notes": result.get("notes", [])[-3:],
        "stderr_tail": str(info.get("judge_stderr", ""))[-700:],
    }


def _check(row: dict[str, Any], label: str, negative_check: str) -> bool:
    checks = row.get("checks") or {}
    if not row.get("done") or row.get("failure_mode") in {None, "", "unknown", "judge_runtime_error"}:
        return False
    if label == "no_op":
        return row["verdict"] == "FAIL" and row["score"] == 0 and row["failure_mode"] == "patch_invalid"
    if label == "plausible_wrong":
        return (
            row["verdict"] == "FAIL" and isinstance(row["score"], (int, float))
            and row["score"] < 1.0 and checks.get("patch_valid") is True
            and checks.get(negative_check) is False
        )
    if label == "transcription":
        # A patch that hard-codes the visible-test outputs must still fail:
        # valid patch format, but the randomized held-out check rejects it.
        return (
            row["verdict"] == "FAIL" and isinstance(row["score"], (int, float))
            and row["score"] < 1.0 and checks.get("patch_valid") is True
            and checks.get(negative_check) is False
        )
    return (row["verdict"] == "PASS" and row["score"] == 1.0
            and row["failure_mode"] == "pass" and checks.get("patch_valid") is True)


def validate_case(
    case: dict[str, Any], *, root: Path = ROOT, include_slow: bool = False,
    timeout: int = 2100,
) -> dict[str, Any]:
    """Grade three variants on a single, identical generated (vector, seed)."""
    environment = str(case.get("environment", ""))
    result: dict[str, Any] = {
        "case_id": case.get("case_id"), "environment": environment,
        "difficulty": case.get("difficulty"), "seed": case.get("seed"),
        "status": "blocked", "provider_calls": 0, "variants": [],
    }
    if environment not in REFERENCES:
        result["reason"] = "reference_not_configured"
        return result
    if environment == "glyph" and not include_slow:
        result["reason"] = "slow_reference_not_run"
        return result
    if root.resolve() != ROOT:
        # env_runner resolves its templates relative to this checkout. Never
        # certify a different checkout using these reference implementations.
        result["reason"] = "root_mismatch"
        return result
    if case.get("config_path") and case.get("config_sha256"):
        config_path = (ROOT / str(case["config_path"])).resolve()
        if not config_path.is_relative_to(ROOT) or not config_path.is_file() or (
            hashlib.sha256(config_path.read_bytes()).hexdigest() != case["config_sha256"]
        ):
            result["reason"] = "pinned_config_drift"
            return result
    entry = REFERENCES[environment]
    apply, negative_check = entry[0], entry[1]
    transcription = entry[2] if len(entry) > 2 else None
    difficulty = case.get("difficulty")
    if not isinstance(difficulty, str) or not difficulty or not isinstance(case.get("seed"), int):
        result["reason"] = "invalid_case_vector"
        return result
    with tempfile.TemporaryDirectory(prefix="instance-oracle-") as temp:
        old_episodes = env_runner.EPISODES_DIR
        try:
            env_runner.EPISODES_DIR = Path(temp) / "episodes"
            episode_id = "oracle_" + uuid.uuid4().hex[:16]
            args = SimpleNamespace(
                episode_id=episode_id, env=environment, difficulty=difficulty,
                seed=case["seed"], max_steps=1, sandbox="local",
                keep_images=False, keep_workspace=True,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner.reset(args)
            state = env_runner._load_state(episode_id)
            result["instance_sha256"] = _instance_hash(state)
            workspace = Path(state["workspace"])
            pristine = Path(state["original_workspace"])
            for label in ("no_op", "plausible_wrong", "transcription", "reference"):
                if label == "transcription":
                    if transcription is None:
                        continue
                    shutil.rmtree(workspace)
                    shutil.copytree(pristine, workspace)
                    transcription(workspace)
                elif label != "no_op":
                    shutil.rmtree(workspace)
                    shutil.copytree(pristine, workspace)
                    apply(workspace, wrong=label == "plausible_wrong")
                row = _run_variant(state, label, timeout=timeout)
                row["expected_failed_check"] = negative_check if label == "plausible_wrong" else None
                row["accepted"] = _check(row, label, negative_check)
                result["variants"].append(row)
                if not row["accepted"]:
                    result["reason"] = f"{label}_did_not_grade_as_expected"
                    break
            else:
                result["status"] = "passed"
        except (OSError, ValueError, RuntimeError, SystemExit) as exc:
            result["reason"] = "oracle_error"
            result["error"] = f"{type(exc).__name__}: {exc}"[-1500:]
        finally:
            env_runner.EPISODES_DIR = old_episodes
    return result


def validate_manifest_instances(
    manifest: dict[str, Any], *, root: Path = ROOT,
    include_slow: bool = False, timeout: int = 2100,
) -> dict[str, Any]:
    """Only a per-case three-variant PASS authorizes that manifest's paid run."""
    cases = list(manifest.get("cases", []))
    if not cases:
        return {"schema_version": 1, "provider_calls": 0,
                "instance_coverage_complete": False, "cases": [], "reason": "no_cases"}
    # Report missing references up front without spending minutes on Glyph for
    # a suite that already cannot be certified. Still report every case.
    missing = [str(c.get("environment")) for c in cases if c.get("environment") not in REFERENCES]
    if missing:
        rows = [validate_case(c, root=root, include_slow=False) if c.get("environment") not in REFERENCES
                else {"case_id": c.get("case_id"), "environment": c.get("environment"),
                      "difficulty": c.get("difficulty"), "seed": c.get("seed"),
                      "status": "blocked", "reason": "not_run_until_all_references_configured",
                      "provider_calls": 0, "variants": []} for c in cases]
    else:
        rows = [validate_case(c, root=root, include_slow=include_slow, timeout=timeout) for c in cases]
    return {
        "schema_version": 1, "provider_calls": 0,
        "instance_coverage_complete": bool(rows) and all(r["status"] == "passed" for r in rows),
        "cases": rows, "missing_references": sorted(set(missing)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="JSON manifest from tools/suite_inventory.py")
    parser.add_argument("--case", action="append", metavar="ENV:VECTOR:SEED",
                        help="e.g. css_state_machine:hard,hard:2 (repeatable)")
    parser.add_argument("--include-slow", action="store_true", help="run Glyph (~8+ minutes) locally")
    parser.add_argument("--out", type=Path, default=Path("runs/instance_oracles.json"))
    args = parser.parse_args(argv)
    if bool(args.manifest) == bool(args.case):
        parser.error("provide exactly one of --manifest or --case")
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    else:
        cases = []
        for entry in args.case:
            environment, difficulty, seed = entry.rsplit(":", 2)
            cases.append({"case_id": entry, "environment": environment,
                          "difficulty": difficulty, "seed": int(seed)})
        manifest = {"cases": cases}
    report = validate_manifest_instances(manifest, include_slow=args.include_slow)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exact-instance oracle report: {args.out}; passed={report['instance_coverage_complete']}")
    return 0 if report["instance_coverage_complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
