"""L1 compiler bootstrapping plus a separate finite opcode-decoding control.

COMPILER_SOURCE is an L1 program compiled by the trusted seed. Running the
result compiles another L1 program to flat VM instructions, including itself.
There is no compile instruction in the VM. Candidate stages are replayed and
tested against the independent source interpreter. Finite challenge agreement
does not prove compiler correctness on every program.
"""
from __future__ import annotations

import copy
import random
from functools import reduce
from operator import index
from typing import Any, Callable, Mapping, Optional


DIRECT = "direct"
RECURSIVE = "recursive"
FLAT = "flat"
REC_COMP = "recursive_composition"
REVEALED = "revealed"
INFERRED = "inferred"
OPCODES = ("push", "add", "halt")
PROGRAM_SAMPLE = 6
MAX_PROGRAM_HEIGHT = 4
GRAMMAR_CONSTANTS = (0, 1, 2)
PUBLIC_KEYS = (
    "modulus",
    "programs",
    "stages",
    "claimed_decoder",
    "calibration",
    "representation",
    "depth",
    "program_height",
    "bootstrap",
)
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "path_vs_local",
    "bootstrap_chain",
    "compiler_semantics",
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
    out = {key: copy.deepcopy(inst[key]) for key in PUBLIC_KEYS if key in inst}
    task = out.get("bootstrap")
    # Supply the trusted executable seed, not the source the agent must author.
    if task is not None:
        out["bootstrap"] = task[:3] + (None,) + task[4:]
    if inst.get("representation") == REVEALED:
        out["encodings"] = copy.deepcopy(inst["encodings"])
    else:
        # Recode permutations reconstruct from encodings; do not leak them when
        # encodings themselves are hidden.
        out["stages"] = [
            {k: copy.deepcopy(v) for k, v in st.items() if k != "perm"}
            for st in (out.get("stages") or [])
        ]
    return out


def grammar_pool(height: int, constants: tuple[int, ...] = GRAMMAR_CONSTANTS) -> list[Any]:
    """Finite add-grammar: constants, then `add(expr, c)` layered up to `height`."""
    height = max(0, int(height))
    layer: list[Any] = [int(c) for c in constants]
    pool: list[Any] = list(layer)
    for _ in range(height):
        nxt = [["add", copy.deepcopy(expr), int(c)] for expr in layer for c in constants]
        pool.extend(nxt)
        layer = nxt
    return pool


def sample_programs(rng: random.Random, height: int, k: int = PROGRAM_SAMPLE) -> list[Any]:
    pool = grammar_pool(height)
    idxs = list(range(len(pool)))
    rng.shuffle(idxs)
    take = min(int(k), len(pool))
    return [copy.deepcopy(pool[i]) for i in idxs[:take]]


def generate_instance(*, depth: int, regime: str, representation: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    modulus = 5
    height = int(depth)
    if height < 1 or height > MAX_PROGRAM_HEIGHT:
        raise OracleBudgetExceeded("supported program height is 1 through 4; no depth saturation")
    programs = sample_programs(rng, height)
    identity = {"push": 0, "add": 1, "halt": 2}
    recode = {0: 2, 1: 0, 2: 1}  # permutation of opcode ids
    composed = permute_encoding(identity, recode)
    # Wrong decoder: swap two codes relative to the true composition
    wrong = {"push": 1, "add": 0, "halt": 2}

    if regime in (DIRECT, FLAT):
        encodings = {"front": identity}
        stages = [{"name": "front", "kind": "compile"}]
        claimed = invert_encoding(identity)
    elif regime == RECURSIVE:
        encodings = {"front": identity, "recode": composed}
        stages = [
            {"name": "front", "kind": "compile"},
            {"name": "recode", "kind": "recode", "perm": dict(recode)},
        ]
        claimed = invert_encoding(composed)
    else:
        encodings = {"front": identity, "recode": composed}
        stages = [
            {"name": "front", "kind": "compile"},
            {"name": "recode", "kind": "recode", "perm": dict(recode)},
        ]
        claimed = invert_encoding(wrong)

    last = stages[-1]["name"]
    calibration = []
    for expr in programs[:3]:
        ops = finalize(compile_source(expr))
        encoded = encode_ops(ops, encodings[last])
        calibration.append({"source": expr, "bytes": encoded})

    return {
        "bootstrap": ("L1-v1", height + 1, seed % 17, COMPILER_SOURCE,
                      BootstrapMachine().seed(COMPILER_SOURCE, seed % 17), height, seed),
        "modulus": modulus,
        "programs": programs,
        "stages": stages,
        "claimed_decoder": {int(k): v for k, v in claimed.items()},
        "calibration": calibration,
        "representation": representation,
        "encodings": encodings,
        "depth": height,
        "program_height": height,
        "meta": {"regime": regime, "seed": seed, "requested_depth": int(depth)},
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
    task = inst["bootstrap"]
    shift = (task[2] + 1 + seed % 16) % 17
    foil["bootstrap"] = task[:2] + (shift, task[3], BootstrapMachine().seed(task[3], shift)) + task[5:]
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
    if inst.get("bootstrap") is not None:
        cert["bootstrap"] = BootstrapMachine().certificate(inst["bootstrap"])
    return cert


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict) or "equivalent" not in raw:
        return False, "equivalent missing"
    if type(raw["equivalent"]) is not bool:
        return False, "equivalent must be a bool"
    if inst.get("bootstrap") is not None:
        if not BootstrapMachine().verify(inst["bootstrap"], raw.get("bootstrap")):
            return 0, "bootstrap chain or held-out semantics failed"
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
    # Invalid source is not evidence against semantic preservation.
    try:
        src = eval_source(expr, modulus, [20_000])
        ops = finalize(compile_source(expr))
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        return 0, "counterexample source is malformed"
    if cex.get("source_value") != src:
        return 0, "counterexample source value mismatch"
    encoded = encode_ops(ops, inst["encodings"][inst["stages"][-1]["name"]])
    decoder = inst["claimed_decoder"]
    try:
        got = eval_bytecode(decode_ops(encoded, decoder), modulus, [20_000])
    except (KeyError, IndexError, ValueError):
        return cex.get("decoded_value") is None, "decoder fails on well-formed source"
    if cex.get("decoded_value") != got:
        return 0, "counterexample decoded value mismatch"
    return src != got, "checked counterexample"


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
    """Negative control: solve the bootstrap, ignore the decoder claim.

    This is a nuisance-certified mutation, not an independent compiler rival.
    """
    return {"equivalent": True, "bootstrap": BootstrapMachine().certificate(inst["bootstrap"])}


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
        checks["bootstrap_chain"] = BootstrapMachine().chain_valid(configured["bootstrap"], first.get("bootstrap"))
        checks["compiler_semantics"] = BootstrapMachine().semantic_valid(configured["bootstrap"], first.get("bootstrap"))
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks


COMPILER_SOURCE = (10, (9, (2, (2, (1,))), (0, 0)), (4, (4, (7, (0, 0), (2, (3, (1,)))), (4, (2, (3, (2, (1,)))), (12,))), (12,)), (10, (9, (2, (2, (1,))), (0, 1)), (4, (4, (7, (0, 1), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,)), (10, (9, (2, (2, (1,))), (0, 12)), (4, (4, (7, (0, 14), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,)), (10, (9, (2, (2, (1,))), (0, 2)), (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (4, (7, (0, 2), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 3)), (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (4, (7, (0, 3), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 6)), (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (4, (7, (0, 6), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 11)), (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (4, (7, (0, 12), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 4)), (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 4), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 5)), (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 5), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 7)), (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 7), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 8)), (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 8), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 9)), (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 9), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 13)), (5, (5, (5, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (4, (7, (0, 15), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,))))), (4, (4, (7, (0, 16), (2, (3, (1,)))), (4, (0, 0), (12,))), (12,))), (10, (9, (2, (2, (1,))), (0, 10)), (13, (4, (11, (4, (2, (3, (2, (1,)))), (4, (2, (3, (1,))), (12,)))), (4, (11, (4, (2, (3, (3, (2, (1,))))), (4, (2, (3, (1,))), (12,)))), (4, (11, (4, (2, (3, (3, (3, (2, (1,)))))), (4, (2, (3, (1,))), (12,)))), (4, (2, (3, (1,))), (12,))))), (5, (5, (5, (5, (2, (1,)), (4, (4, (7, (0, 10), (2, (3, (3, (3, (1,)))))), (4, (7, (6, (2, (3, (1,)))), (0, 1)), (12,))), (12,))), (2, (3, (1,)))), (4, (4, (7, (0, 11), (2, (3, (3, (3, (1,)))))), (4, (6, (2, (3, (3, (1,))))), (12,))), (12,))), (2, (3, (3, (1,)))))), (2, (12,))))))))))))))))


class BootstrapMachine:
    """L1 source evaluator, trusted seed lowering, and a separate flat VM.

    The compiler below is L1 data. No VM instruction compiles source.
    A state is (code, pc, argument, stack, continuation_frames, finished).
    """

    def __init__(self, fuel=200000):
        self.fuel = fuel

    def size(self, value):
        if not value:
            return 0
        return 1 + self.size(value[1:])

    def source(self, expression, argument, program=None):
        self.fuel -= 1
        if self.fuel < 0:
            raise OracleBudgetExceeded("L1 source fuel exhausted")
        if program is None:
            program = expression
        op = expression[0]
        if op == 0:
            return expression[1]
        if op == 1:
            return argument
        if op == 12:
            return ()
        if op == 10:
            branch = 2 if index(self.source(expression[1], argument, program)) else 3
            return self.source(expression[branch], argument, program)
        a = self.source(expression[1], argument, program)
        if op == 2:
            return a[0]
        if op == 3:
            return tuple(a[1:])
        if op == 6:
            return self.size(a)
        if op == 11:
            return self.source(program, a, program)
        if op == 13:
            return self.source(expression[2], a, program)
        b = self.source(expression[2], argument, program)
        if op == 4:
            return (a,) + tuple(b)
        if op == 5:
            return tuple(a) + tuple(b)
        if op == 7:
            return index(a) + index(b)
        if op == 8:
            return index(a) - index(b)
        if op == 9:
            return int(a == b)
        raise ValueError("unknown L1 expression")

    def seed(self, expression, shift=0):
        op = expression[0]
        if op == 0:
            return ((shift, expression[1]),)
        if op == 1:
            return ((shift + 1, 0),)
        if op == 12:
            return ((shift + 14, 0),)
        a = self.seed(expression[1], shift)
        if op == 2 or op == 3 or op == 6:
            return a + ((shift + op, 0),)
        if op == 11:
            return a + ((shift + 12, 0),)
        b = self.seed(expression[2], shift)
        if op == 13:
            return a + ((shift + 15, 0),) + b + ((shift + 16, 0),)
        if op == 10:
            c = self.seed(expression[3], shift)
            return a + ((shift + 10, self.size(b) + 1),) + b + ((shift + 11, self.size(c)),) + c
        if op == 4 or op == 5 or op == 7 or op == 8 or op == 9:
            return a + b + ((shift + op, 0),)
        raise ValueError("unknown seed expression")

    def step(self, state, tick):
        code, pc, argument, stack, frames, finished, shift = state
        if finished:
            return state
        if pc < 0:
            raise ValueError("negative program counter")
        try:
            opcode, operand = code[pc]
            opcode, operand = index(opcode), index(operand)
        except IndexError:
            if pc != self.size(code) or stack[1:]:
                raise ValueError("invalid final stack or jump")
            result = stack[0]
            if not frames:
                return code, pc, argument, stack, frames, 1, shift
            prior_pc, prior_arg, prior_stack = frames[-1]
            return code, prior_pc, prior_arg, prior_stack + (result,), frames[:-1], 0, shift
        opcode -= shift
        pc += 1
        if opcode == 0:
            stack += (operand,)
        elif opcode == 1:
            stack += (argument,)
        elif opcode == 14:
            stack += ((),)
        elif opcode == 2:
            stack = stack[:-1] + (stack[-1][0],)
        elif opcode == 3:
            stack = stack[:-1] + (tuple(stack[-1][1:]),)
        elif opcode == 6:
            stack = stack[:-1] + (self.size(stack[-1]),)
        elif opcode == 10:
            pc += operand if index(stack[-1]) == 0 else 0
            stack = stack[:-1]
        elif opcode == 11:
            pc += operand
        elif opcode == 15:
            stack, argument = stack[:-1] + (argument,), stack[-1]
        elif opcode == 16:
            argument, stack = stack[-2], stack[:-2] + (stack[-1],)
        elif opcode == 12:
            frames += ((pc, argument, stack[:-1]),)
            argument = stack[-1]
            pc, stack = 0, ()
        else:
            a, b = stack[-2:]
            if opcode == 4:
                result = (a,) + tuple(b)
            elif opcode == 5:
                result = tuple(a) + tuple(b)
            elif opcode == 7:
                result = index(a) + index(b)
            elif opcode == 8:
                result = index(a) - index(b)
            elif opcode == 9:
                result = int(a == b)
            else:
                raise ValueError("unknown VM opcode")
            stack = stack[:-2] + (result,)
        return code, pc, argument, stack, frames, 0, shift

    def run(self, code, argument, shift=0):
        state = (tuple(code), 0, argument, (), (), 0, shift)
        return self.execute(state, self.fuel)

    def execute(self, state, remaining):
        if state[5]:
            return state[3][0]
        if remaining <= 0:
            raise OracleBudgetExceeded("L1 VM fuel exhausted")
        block = min(256, remaining)
        state = reduce(self.step, range(block), state)
        return self.execute(state, remaining - block)

    def stages(self, source, previous, remaining, shift):
        if remaining == 0:
            return ()
        current = self.run(previous, (source, shift), shift)
        return (current,) + self.stages(source, current, remaining - 1, shift)

    def check_stages(self, source, previous, submitted, remaining, shift):
        if remaining == 0:
            return int(not submitted)
        if not submitted:
            return 0
        current = tuple(map(tuple, submitted[0]))
        expected = self.run(previous, (source, shift), shift)
        if current != expected:
            return 0
        return self.check_stages(source, current, submitted[1:], remaining - 1, shift)

    def program(self, depth, salt):
        if depth == 0:
            return (7, (1,), (0, salt))
        child = self.program(depth - 1, salt + 1)
        return (10, (9, (1,), (0, salt)), (8, child, (0, salt + 2)), (7, (0, salt), child))

    def semantics(self, compiler, shift, cases):
        if not cases:
            return 1
        expression, argument = cases[0]
        compiled = self.run(compiler, (expression, shift), shift)
        expected = BootstrapMachine().source(expression, argument)
        observed = self.run(compiled, argument, shift)
        if observed != expected:
            return 0
        return self.semantics(compiler, shift, cases[1:])

    def challenges(self, depth, salt):
        recursive_sum = (10, (9, (1,), (0, 0)), (0, 0), (7, (1,), (11, (8, (1,), (0, 1)))))
        return (
            (self.program(depth, salt), salt),
            (self.program(depth + 1, salt + 1), salt + 5),
            ((8, (0, salt), (0, salt + 7)), 0),
            ((10, (0, 0), (2, (12,)), (0, salt)), 0),
            ((2, (3, (4, (0, 3), (4, (0, salt), (12,))))), 0),
            ((6, (5, (4, (0, 1), (12,)), (4, (0, 2), (12,)))), 0),
            ((7, (13, (0, salt + 3), (1,)), (1,)), salt - 2),
            ((10, (0, 1), (0, salt), (2, (12,))), 0),
            (recursive_sum, 4 + salt % 3),
        )

    def certificate(self, task):
        version, count, shift, source, seed, depth, salt = task
        if source is None:
            source = COMPILER_SOURCE
        return source, self.stages(source, seed, count, shift)

    def verify(self, task, certificate):
        return int(self.chain_valid(task, certificate) and self.semantic_valid(task, certificate))

    def chain_valid(self, task, certificate):
        version, count, shift, source, seed, depth, salt = task
        try:
            proposed_source, stages = certificate
            proposed_source = self.syntax(proposed_source)
            if version != "L1-v1" or count < 2:
                return 0
            return self.check_stages(proposed_source, seed, stages, count, shift)
        except (IndexError, KeyError, TypeError, ValueError, RecursionError, OracleBudgetExceeded):
            return 0

    def stage_semantics(self, stages, shift, salt):
        if not stages:
            return 1
        if not self.semantics(stages[0], shift, self.challenges(1, salt)):
            return 0
        return self.stage_semantics(stages[1:], shift, salt + 1)

    def semantic_valid(self, task, certificate):
        version, count, shift, source, seed, depth, salt = task
        try:
            proposed_source, stages = certificate
            if not stages:
                return 0
            if not self.stage_semantics(stages, shift, 37):
                return 0
            return self.semantics(stages[-1], shift, self.challenges(depth, salt + 104729))
        except (IndexError, KeyError, TypeError, ValueError, RecursionError, OracleBudgetExceeded):
            return 0

    def syntax(self, expression):
        """Validate the AST grammar and canonicalize its JSON sequences."""
        op = index(expression[0])
        if op == 0:
            tag, value = expression
            return tag, index(value)
        if op == 1 or op == 12:
            tag, = expression
            return (tag,)
        if op == 2 or op == 3 or op == 6 or op == 11:
            tag, child = expression
            return tag, self.syntax(child)
        if op == 10:
            tag, condition, yes, no = expression
            return tag, self.syntax(condition), self.syntax(yes), self.syntax(no)
        if op == 4 or op == 5 or op == 7 or op == 8 or op == 9 or op == 13:
            tag, left, right = expression
            return tag, self.syntax(left), self.syntax(right)
        raise ValueError("unknown L1 source tag")
