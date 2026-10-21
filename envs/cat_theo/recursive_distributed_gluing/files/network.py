"""Recursive distributed gluing: nested workers, messages, a mutex, a schedule.

A solution is an execution trace, not the numeric result alone. The independent
oracle searches interleavings of the declared programs under mutex and mailbox
causality. Timeout is not unsat.
"""
from __future__ import annotations

import copy
import random
from collections import deque
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSPARENT = "transparent"
OPAQUE = "opaque"
PUBLIC_KEYS = ("modulus", "input", "workers", "lock_count", "root")
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. This is not evidence of unsatisfiability."""


def public_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return {key: job[key] for key in PUBLIC_KEYS}


def _tokens(rng: random.Random, n: int, used: set[str]) -> list[str]:
    out = []
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while len(out) < n:
        tok = "".join(rng.choice(alphabet) for _ in range(5))
        if tok not in used:
            used.add(tok)
            out.append(tok)
    return out


def generate_job(
    *,
    depth: int,
    regime: str,
    opacity: str,
    seed: int,
    modulus: int = 4,
    lock_count: int = 1,
) -> dict[str, Any]:
    if depth < 1:
        raise ValueError("depth")
    rng = random.Random(seed)
    used: set[str] = set()
    if opacity == TRANSPARENT:
        names = ["root"] + [f"w{i}" for i in range(1, depth + 1)]
    else:
        names = _tokens(rng, depth + 1, used)

    workers = {}
    for i, name in enumerate(names):
        parent = None if i == 0 else names[i - 1]
        child = names[i + 1] if i < depth else None
        if child is None:
            if regime == CYCLIC_UNSAT:
                program = ["lock", "recv:parent", "send:parent", "unlock"]
            elif regime == CYCLIC_SAT:
                program = ["send:parent", "recv:parent", "lock", "compute", "unlock"]
            else:
                program = ["lock", "compute", "unlock", "send:parent"]
        elif regime == CYCLIC_UNSAT and i == 0:
            program = ["spawn", "lock", "recv:child", "send:child", "unlock"]
        elif regime == CYCLIC_SAT:
            program = (
                ["spawn", "recv:child", "send:child", "compute"]
                if i == 0
                else ["spawn", "recv:child", "send:child", "compute", "send:parent"]
            )
        elif i == 0:
            program = ["spawn", "recv:child", "compute"]
        else:
            program = ["spawn", "recv:child", "compute", "send:parent"]
        workers[name] = {
            "parent": parent,
            "child": child,
            "program": program,
        }
    return {
        "modulus": int(modulus),
        "input": 1,
        "lock_count": int(lock_count),
        "workers": workers,
        "root": names[0],
        "meta": {"regime": regime, "opacity": opacity, "depth": depth},
    }


def relabel_job(job: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    used: set[str] = set()
    old_names = list(job["workers"])
    mapping = {old: _tokens(rng, 1, used)[0] for old in old_names}
    workers = {}
    for old, spec in job["workers"].items():
        workers[mapping[old]] = {
            "parent": None if spec["parent"] is None else mapping[spec["parent"]],
            "child": None if spec["child"] is None else mapping[spec["child"]],
            "program": list(spec["program"]),
        }
    return {
        "modulus": job["modulus"],
        "input": job["input"],
        "lock_count": job["lock_count"],
        "workers": workers,
        "root": mapping[job["root"]],
        "meta": dict(job.get("meta") or {}),
    }


def example_visible_job() -> dict[str, Any]:
    return {
        "modulus": 4,
        "input": 1,
        "lock_count": 1,
        "root": "root",
        "workers": {
            "root": {"parent": None, "child": "leaf", "program": ["spawn", "recv:child", "compute"]},
            "leaf": {"parent": "root", "child": None, "program": ["compute", "send:parent"]},
        },
    }


def _resolve(agent: str, spec: Mapping[str, Any], target: str) -> Optional[str]:
    if target == "parent":
        return spec["parent"]
    if target == "child":
        return spec["child"]
    if target == agent:
        return agent
    return target if target in (spec["parent"], spec["child"]) else None


def replay_trace(job: Mapping[str, Any], trace: list, max_events: int = 10_000) -> tuple[bool, str, Optional[int]]:
    workers = job["workers"]
    modulus = int(job["modulus"])
    if not isinstance(trace, list) or len(trace) > max_events:
        return False, "trace missing or too long", None
    pc = {name: 0 for name in workers}
    inbox = {name: None for name in workers}
    inbox[job["root"]] = int(job["input"]) % modulus
    value = {name: None for name in workers}
    last_recv = {name: None for name in workers}
    mail: dict[tuple[str, str], list[int]] = {}
    spawned = {name: False for name in workers}
    lock_held = 0
    lock_limit = int(job["lock_count"])
    holding = {name: False for name in workers}

    def take_mail(src: str, dst: str) -> Optional[int]:
        key = (src, dst)
        buf = mail.get(key) or []
        if not buf:
            return None
        payload = buf.pop(0)
        mail[key] = buf
        return payload

    for i, ev in enumerate(trace):
        if not isinstance(ev, dict) or "agent" not in ev or "op" not in ev:
            return False, f"event {i} malformed", None
        agent = str(ev["agent"])
        if agent not in workers:
            return False, f"event {i}: unknown agent", None
        spec = workers[agent]
        program = spec["program"]
        if pc[agent] >= len(program):
            return False, f"event {i}: {agent} already finished", None
        expected = program[pc[agent]]
        op = str(ev["op"])
        if expected != op and not (expected.startswith("send:") and op.startswith("send:")):
            if expected != op:
                return False, f"event {i}: {agent} expected {expected}, got {op}", None
        if expected.startswith("send:") or expected.startswith("recv:"):
            if op != expected:
                return False, f"event {i}: {agent} expected {expected}", None
        if op == "spawn":
            child = spec["child"]
            if child is None:
                return False, f"event {i}: no child", None
            if inbox[agent] is None:
                return False, f"event {i}: spawn without input", None
            inbox[child] = inbox[agent]
            spawned[agent] = True
        elif op == "lock":
            if holding[agent] or lock_held >= lock_limit:
                return False, f"event {i}: lock unavailable", None
            holding[agent] = True
            lock_held += 1
        elif op == "unlock":
            if not holding[agent]:
                return False, f"event {i}: unlock without lock", None
            holding[agent] = False
            lock_held -= 1
        elif op == "compute":
            base = inbox[agent]
            extra = last_recv[agent]
            if base is None:
                return False, f"event {i}: compute without input", None
            if spec["child"] is not None:
                if extra is None:
                    return False, f"event {i}: compute without child result", None
                value[agent] = (base + extra) % modulus
            else:
                value[agent] = (base + 1) % modulus
        elif op.startswith("send:"):
            target = _resolve(agent, spec, op.split(":", 1)[1])
            if target is None:
                return False, f"event {i}: bad send target", None
            payload = value[agent] if value[agent] is not None else inbox[agent]
            if payload is None:
                return False, f"event {i}: send without payload", None
            mail.setdefault((agent, target), []).append(int(payload) % modulus)
        elif op.startswith("recv:"):
            source_role = op.split(":", 1)[1]
            source = _resolve(agent, spec, source_role)
            if source is None:
                return False, f"event {i}: bad recv source", None
            payload = take_mail(source, agent)
            if payload is None:
                return False, f"event {i}: empty mailbox", None
            last_recv[agent] = payload
            if inbox[agent] is None:
                inbox[agent] = payload
        else:
            return False, f"event {i}: unknown op", None
        pc[agent] += 1

    if any(holding.values()):
        return False, "locks still held", None
    if any(pc[name] != len(workers[name]["program"]) for name in workers):
        return False, "program unfinished", None
    root = job["root"]
    result = value[root]
    if result is None:
        result = last_recv[root]
    if result is None:
        return False, "no root result", None
    return True, "ok", int(result)


def _enabled(job, pc, inbox, value, last_recv, mail, lock_held, holding, spawned):
    workers = job["workers"]
    lock_limit = int(job["lock_count"])
    enabled = []
    for name, spec in workers.items():
        if pc[name] >= len(spec["program"]):
            continue
        op = spec["program"][pc[name]]
        if op == "spawn":
            if inbox[name] is None:
                continue
            enabled.append(name)
        elif op == "lock":
            if not holding[name] and lock_held < lock_limit:
                enabled.append(name)
        elif op == "unlock":
            if holding[name]:
                enabled.append(name)
        elif op == "compute":
            if inbox[name] is None:
                continue
            if spec["child"] is not None and last_recv[name] is None:
                continue
            enabled.append(name)
        elif op.startswith("send:"):
            payload = value[name] if value[name] is not None else inbox[name]
            if payload is None:
                continue
            enabled.append(name)
        elif op.startswith("recv:"):
            source = _resolve(name, spec, op.split(":", 1)[1])
            if source is None:
                continue
            if mail.get((source, name)):
                enabled.append(name)
        else:
            continue
    return enabled


def shortest_trace(job: Mapping[str, Any], max_nodes: int = 80_000) -> Optional[list[dict[str, str]]]:
    workers = job["workers"]
    names = tuple(sorted(workers))
    modulus = int(job["modulus"])
    start_inbox = {name: None for name in workers}
    start_inbox[job["root"]] = int(job["input"]) % modulus
    start = (
        tuple(0 for _ in names),
        tuple(start_inbox[n] for n in names),
        tuple(None for _ in names),
        tuple(None for _ in names),
        tuple(),
        0,
        tuple(False for _ in names),
    )
    queue = deque([start])
    prev: dict[tuple, tuple[Any, dict]] = {}
    seen = {start}
    nodes = 0
    goal = None
    index = {n: i for i, n in enumerate(names)}

    def freeze_mail(mail: dict) -> tuple:
        items = []
        for key, buf in mail.items():
            if buf:
                items.append((key[0], key[1], tuple(buf)))
        return tuple(sorted(items))

    def thaw_mail(frozen: tuple) -> dict:
        mail = {}
        for a, b, buf in frozen:
            mail[(a, b)] = list(buf)
        return mail

    while queue:
        state = queue.popleft()
        nodes += 1
        if nodes > max_nodes:
            raise OracleBudgetExceeded(
                f"distributed oracle exceeded {max_nodes} states; refusing to call this unsat"
            )
        pcs, inb, vals, recvs, mail_f, lock_held, holding = state
        if all(pcs[index[n]] == len(workers[n]["program"]) for n in names) and lock_held == 0:
            goal = state
            break
        inbox = {n: inb[index[n]] for n in names}
        value = {n: vals[index[n]] for n in names}
        last_recv = {n: recvs[index[n]] for n in names}
        mail = thaw_mail(mail_f)
        hold_map = {n: holding[index[n]] for n in names}
        pcmap = {n: pcs[index[n]] for n in names}
        for agent in _enabled(job, pcmap, inbox, value, last_recv, mail, lock_held, hold_map, {}):
            spec = workers[agent]
            op = spec["program"][pcmap[agent]]
            event = {"agent": agent, "op": op}
            # apply a copy
            inbox2 = dict(inbox)
            value2 = dict(value)
            last2 = dict(last_recv)
            mail2 = {k: list(v) for k, v in mail.items()}
            hold2 = dict(hold_map)
            lock2 = lock_held
            pc2 = dict(pcmap)
            if op == "spawn":
                inbox2[spec["child"]] = inbox2[agent]
            elif op == "lock":
                hold2[agent] = True
                lock2 += 1
            elif op == "unlock":
                hold2[agent] = False
                lock2 -= 1
            elif op == "compute":
                if spec["child"] is not None:
                    value2[agent] = (inbox2[agent] + last2[agent]) % modulus
                else:
                    value2[agent] = (inbox2[agent] + 1) % modulus
            elif op.startswith("send:"):
                target = _resolve(agent, spec, op.split(":", 1)[1])
                payload = value2[agent] if value2[agent] is not None else inbox2[agent]
                mail2.setdefault((agent, target), []).append(int(payload) % modulus)
            elif op.startswith("recv:"):
                source = _resolve(agent, spec, op.split(":", 1)[1])
                buf = mail2.get((source, agent)) or []
                payload = buf.pop(0)
                mail2[(source, agent)] = buf
                last2[agent] = payload
                if inbox2[agent] is None:
                    inbox2[agent] = payload
            pc2[agent] += 1
            nxt = (
                tuple(pc2[n] for n in names),
                tuple(inbox2[n] for n in names),
                tuple(value2[n] for n in names),
                tuple(last2[n] for n in names),
                freeze_mail(mail2),
                lock2,
                tuple(hold2[n] for n in names),
            )
            if nxt in seen:
                continue
            seen.add(nxt)
            prev[nxt] = (state, event)
            queue.append(nxt)
    if goal is None:
        return None
    steps = []
    cur: Any = goal
    while cur != start:
        parent, event = prev[cur]
        steps.append(event)
        cur = parent
    steps.reverse()
    return steps


def job_satisfiable(job: Mapping[str, Any]) -> bool:
    return shortest_trace(job) is not None


def reference_certificate(job: Mapping[str, Any]) -> dict[str, Any]:
    trace = shortest_trace(job)
    if trace is None:
        return {"status": "unsat"}
    ok, _reason, result = replay_trace(job, trace)
    if not ok:
        raise RuntimeError("reference trace failed replay")
    return {"status": "sat", "trace": trace, "result": result}


def parse_certificate(raw: Any) -> tuple[Optional[dict[str, Any]], str]:
    if not isinstance(raw, dict):
        return None, "not a dict"
    if raw.get("status") == "unsat":
        return {"status": "unsat"}, ""
    if raw.get("status") != "sat":
        return None, "status"
    if not isinstance(raw.get("trace"), list):
        return None, "sat needs trace"
    return {"status": "sat", "trace": raw["trace"], "result": raw.get("result")}, ""


def verify_certificate(job: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    cert, err = parse_certificate(raw)
    if cert is None:
        return False, err
    sat = job_satisfiable(job)
    if cert["status"] == "unsat":
        return (not sat, "unsat but a schedule exists" if sat else "ok")
    if not sat:
        return False, "sat but no schedule exists"
    ok, reason, result = replay_trace(job, cert["trace"])
    if not ok:
        return False, reason
    if cert.get("result") is not None and int(cert["result"]) != int(result):
        return False, "result does not match the trace"
    return True, "ok"


def arm_reference(job: Mapping[str, Any]) -> dict[str, Any]:
    return reference_certificate(job)


def arm_numbers_only(job: Mapping[str, Any]) -> dict[str, Any]:
    """Baseline analogue: invent a result, ignore programs/locks."""
    return {"status": "sat", "trace": [], "result": int(job["input"])}


def evaluate_solver(solve_fn: Callable, job: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_job(job)))
    except Exception:
        return False
    ok, _ = verify_certificate(job, raw)
    return ok


def build_grade_jobs(*, depth: int, regime: str, opacity: str, seed: int) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_job(depth=depth, regime=regime, opacity=opacity, seed=seed)
    return [
        ("local_visible", example_visible_job()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_job(depth=max(depth, 1), regime=CYCLIC_SAT, opacity=opacity, seed=seed + 11),
        ),
        (
            "assembled_unsat",
            generate_job(depth=max(depth, 1), regime=CYCLIC_UNSAT, opacity=opacity, seed=seed + 13),
        ),
        ("opaque_twin", relabel_job(configured, seed + 99)),
    ]


def grade_solver(solve_fn: Callable, *, depth: int, regime: str, opacity: str, seed: int) -> dict[str, bool]:
    items = build_grade_jobs(depth=depth, regime=regime, opacity=opacity, seed=seed)
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, job in items:
        checks[name] = evaluate_solver(solve_fn, job)
    configured = named["configured"]
    try:
        pub = public_job(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks
