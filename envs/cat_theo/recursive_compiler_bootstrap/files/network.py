"""Tiny source language, stack bytecode, and bootstrap encodings.

Source expressions are integers or binary `add` nodes, evaluated modulo p.
Bytecode is push/add/halt on a stack. A compiler stage is a total map from
source (or bytecode) to bytecode together with an opcode encoding. Local
stage contracts are checked by running both interpreters on a declared finite
program set. A bootstrap claim names a decoder for a composed path; it can
fail observational equivalence even when each stage is locally correct
relative to its own encoding.

This is not a holonomy/CSP solver: the oracle executes programs.
"""
from __future__ import annotations

import copy
import random
from typing import Any, Callable, Mapping, Optional


DIRECT = "direct"
RECURSIVE = "recursive"
FLAT = "flat"
REC_COMP = "recursive_composition"
REVEALED = "revealed"
INFERRED = "inferred"
OPCODES = ("push", "add", "halt")
PUBLIC_KEYS = (
    "modulus",
    "programs",
    "stages",
    "claimed_decoder",
    "calibration",
    "representation",
)
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "path_vs_local",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. Not evidence that the bootstrap claim is false."""


def eval_source(expr: Any, modulus: int, budget: list[int]) -> int:
    budget[0] -= 1
    if budget[0] < 0:
        raise OracleBudgetExceeded("interpreter exceeded step budget; refusing to call this unsat")
    if isinstance(expr, int):
        return int(expr) % modulus
    if isinstance(expr, list) and expr and expr[0] == "add":
        return (eval_source(expr[1], modulus, budget) + eval_source(expr[2], modulus, budget)) % modulus
    raise ValueError("bad source")


def compile_source(expr: Any) -> list[list[Any]]:
    if isinstance(expr, int):
        return [["push", int(expr)], ["halt"]] if False else [["push", int(expr)]]
    left = compile_source(expr[1])
    right = compile_source(expr[2])
    return left + right + [["add"]]


def finalize(ops: list[list[Any]]) -> list[list[Any]]:
    if ops and ops[-1] == ["halt"]:
        return ops
    return ops + [["halt"]]


def eval_bytecode(ops: list, modulus: int, budget: list[int]) -> int:
    stack: list[int] = []
    for op in ops:
        budget[0] -= 1
        if budget[0] < 0:
            raise OracleBudgetExceeded("bytecode exceeded step budget; refusing to call this unsat")
        if op[0] == "push":
            stack.append(int(op[1]) % modulus)
        elif op[0] == "add":
            if len(stack) < 2:
                raise ValueError("stack")
            b = stack.pop()
            a = stack.pop()
            stack.append((a + b) % modulus)
        elif op[0] == "halt":
            if not stack:
                raise ValueError("empty")
            return stack[-1]
        else:
            raise ValueError(op[0])
    if not stack:
        raise ValueError("no halt")
    return stack[-1]


def encode_ops(ops: list, encoding: Mapping[str, int]) -> list[list[Any]]:
    out = []
    for op in ops:
        code = int(encoding[op[0]])
        if op[0] == "push":
            out.append([code, int(op[1])])
        else:
            out.append([code])
    return out


def decode_ops(raw: list, decoder: Mapping[int, str]) -> list[list[Any]]:
    out = []
    for op in raw:
        name = decoder[int(op[0])]
        if name == "push":
            out.append(["push", int(op[1])])
        else:
            out.append([name])
    return out


def invert_encoding(encoding: Mapping[str, int]) -> dict[int, str]:
    return {int(v): k for k, v in encoding.items()}


def permute_encoding(base: Mapping[str, int], perm: Mapping[int, int]) -> dict[str, int]:
    return {name: int(perm[int(code)]) for name, code in base.items()}


def public_instance(inst: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: copy.deepcopy(inst[key]) for key in PUBLIC_KEYS}
    if inst.get("representation") == REVEALED:
        out["encodings"] = copy.deepcopy(inst["encodings"])
    return out


def generate_instance(*, depth: int, regime: str, representation: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    modulus = 5
    programs = [0, 1, 2, ["add", 1, 2], ["add", ["add", 1, 0], 3], ["add", 4, 4]]
    identity = {"push": 0, "add": 1, "halt": 2}
    recode = {0: 2, 1: 0, 2: 1}  # permutation of opcode ids
    composed = permute_encoding(identity, recode)
    # Wrong decoder: swap two codes relative to the true composition
    wrong = {"push": 1, "add": 0, "halt": 2}

    if regime in (DIRECT, FLAT):
        encodings = {"front": identity}
        stages = [{"name": "front", "kind": "compile"}]
        claimed = invert_encoding(identity)
        depth_used = 1
    elif regime == RECURSIVE:
        encodings = {"front": identity, "recode": composed}
        stages = [
            {"name": "front", "kind": "compile"},
            {"name": "recode", "kind": "recode", "perm": dict(recode)},
        ]
        claimed = invert_encoding(composed)
        depth_used = max(depth, 2)
    else:
        encodings = {"front": identity, "recode": composed}
        stages = [
            {"name": "front", "kind": "compile"},
            {"name": "recode", "kind": "recode", "perm": dict(recode)},
        ]
        claimed = invert_encoding(wrong)
        depth_used = max(depth, 2)

    calibration = []
    for expr in programs[:3]:
        ops = finalize(compile_source(expr))
        encoded = encode_ops(ops, encodings[stages[-1]["name"] if regime != DIRECT else "front"])
        if regime in (RECURSIVE, REC_COMP):
            ops = finalize(compile_source(expr))
            encoded = encode_ops(ops, encodings["recode"])
        calibration.append({"source": expr, "bytes": encoded})

    return {
        "modulus": modulus,
        "programs": programs,
        "stages": stages,
        "claimed_decoder": {int(k): v for k, v in claimed.items()},
        "calibration": calibration,
        "representation": representation,
        "encodings": encodings,
        "depth": depth_used,
        "meta": {"regime": regime, "seed": seed},
    }


def path_observationally_equivalent(inst: Mapping[str, Any], decoder: Mapping[Any, str], budget: int = 20_000) -> bool:
    modulus = int(inst["modulus"])
    encodings = inst["encodings"]
    last = inst["stages"][-1]["name"]
    encoding = encodings[last]
    for expr in inst["programs"]:
        src = eval_source(expr, modulus, [budget])
        ops = finalize(compile_source(expr))
        encoded = encode_ops(ops, encoding)
        try:
            decoded = decode_ops(encoded, {int(k): v for k, v in decoder.items()})
            got = eval_bytecode(decoded, modulus, [budget])
        except (KeyError, IndexError, ValueError):
            return False
        if src != got:
            return False
    return True


def stage_locally_ok(inst: Mapping[str, Any], budget: int = 20_000) -> bool:
    """Each stage preserves source observations under *its own* encoding."""
    modulus = int(inst["modulus"])
    for name, encoding in inst["encodings"].items():
        decoder = invert_encoding(encoding)
        for expr in inst["programs"]:
            src = eval_source(expr, modulus, [budget])
            ops = finalize(compile_source(expr))
            encoded = encode_ops(ops, encoding)
            got = eval_bytecode(decode_ops(encoded, decoder), modulus, [budget])
            if src != got:
                return False
    return True


def claim_holds(inst: Mapping[str, Any]) -> bool:
    return path_observationally_equivalent(inst, inst["claimed_decoder"])


def relabel_instance(inst: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    perm = list(range(3))
    rng.shuffle(perm)
    mapping = {i: perm[i] for i in range(3)}
    foil = copy.deepcopy(inst)
    new_enc = {}
    for name, enc in inst["encodings"].items():
        new_enc[name] = permute_encoding(enc, mapping)
    foil["encodings"] = new_enc
    last = inst["stages"][-1]["name"]
    if inst["meta"]["regime"] == REC_COMP:
        # keep the claim wrong in the new labels: invert a still-wrong encoding
        wrong_ids = {mapping[int(k)]: v for k, v in inst["claimed_decoder"].items()}
        foil["claimed_decoder"] = wrong_ids
    else:
        foil["claimed_decoder"] = invert_encoding(new_enc[last])
    foil["calibration"] = []
    for expr in inst["programs"][:3]:
        ops = finalize(compile_source(expr))
        encoded = encode_ops(ops, new_enc[last])
        foil["calibration"].append({"source": expr, "bytes": encoded})
    return foil


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(depth=1, regime=DIRECT, representation=REVEALED, seed=0)


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    holds = claim_holds(inst)
    cert: dict[str, Any] = {"equivalent": bool(holds)}
    if not holds:
        modulus = int(inst["modulus"])
        decoder = {int(k): v for k, v in inst["claimed_decoder"].items()}
        last = inst["stages"][-1]["name"]
        encoding = inst["encodings"][last]
        for expr in inst["programs"]:
            src = eval_source(expr, modulus, [20_000])
            ops = finalize(compile_source(expr))
            encoded = encode_ops(ops, encoding)
            try:
                got = eval_bytecode(decode_ops(encoded, decoder), modulus, [20_000])
            except (KeyError, IndexError, ValueError):
                cert["counterexample"] = {"source": expr, "source_value": src, "decoded_value": None}
                break
            if src != got:
                cert["counterexample"] = {"source": expr, "source_value": src, "decoded_value": got}
                break
    else:
        cert["encodings"] = copy.deepcopy(inst["encodings"])
    return cert


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict) or "equivalent" not in raw:
        return False, "equivalent missing"
    if type(raw["equivalent"]) is not bool:
        return False, "equivalent must be a bool"
    true = claim_holds(inst)
    if raw["equivalent"] is not true:
        return False, "equivalent mismatch"
    if true:
        return True, "ok"
    cex = raw.get("counterexample")
    if not isinstance(cex, dict) or "source" not in cex:
        return False, "counterexample missing"
    modulus = int(inst["modulus"])
    expr = cex["source"]
    try:
        src = eval_source(expr, modulus, [20_000])
        ops = finalize(compile_source(expr))
        encoded = encode_ops(ops, inst["encodings"][inst["stages"][-1]["name"]])
        decoder = {int(k): v for k, v in inst["claimed_decoder"].items()}
        got = eval_bytecode(decode_ops(encoded, decoder), modulus, [20_000])
    except (KeyError, IndexError, ValueError, OracleBudgetExceeded):
        return True, "ok"
    if src == got:
        return False, "cited program does not disagree"
    return True, "ok"


def evaluate_solver(solve_fn: Callable, inst: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_instance(inst)))
    except Exception:
        return False
    ok, _ = verify_certificate(inst, raw)
    return ok


def arm_reference(inst: Mapping[str, Any]) -> dict[str, Any]:
    return reference_certificate(inst)


def arm_local_only(inst: Mapping[str, Any]) -> dict[str, Any]:
    """Baseline: every local stage ok => claim the path is equivalent."""
    return {"equivalent": True}


def build_grade_items(*, depth: int, regime: str, representation: str, seed: int) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_instance(depth=depth, regime=regime, representation=representation, seed=seed)
    return [
        ("local_visible", example_visible_instance()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_instance(depth=max(depth, 2), regime=RECURSIVE, representation=representation, seed=seed + 11),
        ),
        (
            "assembled_unsat",
            generate_instance(depth=max(depth, 2), regime=REC_COMP, representation=representation, seed=seed + 13),
        ),
        ("opaque_twin", relabel_instance(configured, seed + 99)),
        ("path_vs_local", generate_instance(depth=2, regime=REC_COMP, representation=REVEALED, seed=seed + 17)),
    ]


def grade_solver(solve_fn: Callable, *, depth: int, regime: str, representation: str, seed: int) -> dict[str, bool]:
    items = build_grade_items(depth=depth, regime=regime, representation=representation, seed=seed)
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, inst in items:
        checks[name] = evaluate_solver(solve_fn, inst)
    configured = named["configured"]
    try:
        pub = public_instance(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks
