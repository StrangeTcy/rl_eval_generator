"""Independent verification tooling for the epistemic families (V1/V3).

Source grounding (Mission 02 portfolio):

* V1 - Faithfulness of English renderings: "Given an instance's English text
  without generator metadata or answer, how often do independent annotators
  reconstruct the registered formal state and queried proposition exactly?"
  Operationalized here as a deterministic structural parse of the public
  task.md followed by an exact-match comparison against the judge-side
  formal specification. Predefined treatment: any parse mismatch is recorded
  as a faithfulness failure with an error type; there is no adjudication
  step because annotation is mechanical.

* V3 - Feasibility of independent verification: "Can the chosen family
  support a verifier that does not share the generator implementation?"
  Operationalized here as a ground-truth recomputation driven ONLY by the
  parsed public text and the accepted shared substrate modules
  (shared/epistemic_semantics). This tool never imports any family core.py
  and never reads judge internals beyond the baked specification used as
  the comparison reference.

Independence statement: the surface-vocabulary tables below mirror the
public rendering vocabulary (agent-visible strings) as data only; they carry
no generation, sampling, or grading logic. A drift test in
tests/test_epistemic_verification.py pins them to the family vocabularies.

Notably, E2 ground truth is recomputed WITHOUT the hidden actual world:
the verifier restricts the initial world set announcement by announcement
and then uses the public-derivability invariant (query truth constant across
the final survivors) - a strictly weaker-information path than the judge's.
"""
from __future__ import annotations

import argparse
import ast
import itertools
import json
import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.epistemic_semantics import event_bayes  # noqa: E402
from shared.epistemic_semantics import fragmented_observation as CSO  # noqa: E402

SpecError = event_bayes.SpecError
from shared.epistemic_semantics import public_announcements as PAL  # noqa: E402
from shared.epistemic_semantics import silence as SILENCE  # noqa: E402
from shared.epistemic_semantics import supplied_policy as POLICY  # noqa: E402

Struct = Tuple  # ("atom", prop) | ("neg", s) | ("knows", agent, s) | ("joint_entails", s)


class VerificationError(RuntimeError):
    """Raised for unrecoverable parse or comparison failures."""


# ---------------------------------------------------------------------------
# Surface vocabulary (public rendering data only; see module docstring).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceVocab:
    agent_names: Dict[str, str]
    world_labels: Tuple[str, ...]
    atom_texts: Dict[str, str]


E2_E4_E5_VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        agent_names={"a": "Alice", "b": "Bob"},
        world_labels=(
            "the archive room", "the print room", "the server room",
            "the records vault", "the mail room", "the loading dock",
        ),
        atom_texts={"p": "the ledger was updated", "q": "the nightly backup ran"},
    ),
    "expedition": SurfaceVocab(
        agent_names={"a": "Anders", "b": "Bek"},
        world_labels=(
            "the ridge camp", "the river fork", "the glacier shelf",
            "the moraine", "the icefall", "the summit saddle",
        ),
        atom_texts={"p": "the supply cache was moved", "q": "the radio check-in happened"},
    ),
}

E3_VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        agent_names={"a": "Alice", "b": "Bob"},
        world_labels=(
            "the ledger was updated",
            "the nightly backup ran",
            "neither the ledger update nor the backup ran",
        ),
        atom_texts={},
    ),
    "expedition": SurfaceVocab(
        agent_names={"a": "Anders", "b": "Bek"},
        world_labels=(
            "the supply cache was moved",
            "the radio check-in happened",
            "neither the cache move nor the check-in happened",
        ),
        atom_texts={},
    ),
}


def _agent_ids(vocab: SurfaceVocab) -> Dict[str, str]:
    return {name: agent for agent, name in vocab.agent_names.items()}


def _atom_ids(vocab: SurfaceVocab) -> Dict[str, str]:
    return {text: atom for atom, text in vocab.atom_texts.items()}


# ---------------------------------------------------------------------------
# Formula surface parser (recursive descent over the public grammar).
# ---------------------------------------------------------------------------

def parse_formula(text: str, vocab: SurfaceVocab) -> Struct:
    text = text.strip().rstrip("?").strip()
    neg_prefix = "it is not the case that "
    if text.startswith(neg_prefix):
        return ("neg", parse_formula(text[len(neg_prefix):], vocab))
    knows_marker = " knows that "
    for name, agent in sorted(_agent_ids(vocab).items(), key=lambda kv: -len(kv[0])):
        prefix = f"{name}{knows_marker}"
        if text.startswith(prefix):
            return ("knows", agent, parse_formula(text[len(prefix):], vocab))
    joint_prefix = "pooling "
    if text.startswith(joint_prefix):
        marker = "'s observations pins down that "
        idx = text.find(marker)
        if idx == -1:
            raise VerificationError(f"malformed pooling phrase: {text!r}")
        return ("joint_entails", parse_formula(text[idx + len(marker):], vocab))
    for atom_text, atom in _atom_ids(vocab).items():
        if text == atom_text:
            return ("atom", atom)
    raise VerificationError(f"unrecognized formula surface: {text!r}")


def formula_to_list(struct: Struct) -> list:
    return list(struct)


# ---------------------------------------------------------------------------
# Shared block parsers.
# ---------------------------------------------------------------------------

def _section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", re.M | re.S)
    match = pattern.search(text)
    if not match:
        raise VerificationError(f"missing section {heading!r}")
    return match.group(1).strip()


def _parse_world_valuation(block: str, vocab: SurfaceVocab) -> Dict[str, List[str]]:
    """Parse '- `w1` (label): fact; fact.' lines into sorted atom lists."""
    valuation: Dict[str, List[str]] = {}
    label_to_index = {label: i for i, label in enumerate(vocab.world_labels)}
    atom_by_text = _atom_ids(vocab)
    line_re = re.compile(r"^- `(w\d+)` \(([^)]+)\): (.+)\.$", re.M)
    for world, label, facts in line_re.findall(block):
        if label_to_index.get(label) != int(world[1:]) - 1:
            raise VerificationError(f"world/label mismatch: {world} ({label})")
        atoms = []
        if facts != "no listed facts":
            for fact in facts.split("; "):
                if fact not in atom_by_text:
                    raise VerificationError(f"unknown fact text: {fact!r}")
                atoms.append(atom_by_text[fact])
        valuation[world] = sorted(atoms)
    return valuation


def _parse_partition_lines(block: str, vocab: SurfaceVocab, verb_exact: str,
                          verb_group: str) -> Dict[str, List[List[str]]]:
    """Parse '- Name: cannot distinguish w1 from w2; identifies w3 exactly.'."""
    partitions: Dict[str, List[List[str]]] = {}
    agents = _agent_ids(vocab)
    line_re = re.compile(r"^- ([^:`]+): (.+)\.$", re.M)
    for name, body in line_re.findall(block):
        if name not in agents:
            continue  # non-agent list lines (e.g. valuations) are out of scope
        cells: List[List[str]] = []
        for part in body.split("; "):
            if part.startswith(verb_group + " "):
                worlds = part[len(verb_group) + 1:].split(" from ")
                cells.append(sorted(worlds))
            elif part.startswith(verb_exact + " "):
                rest = part[len(verb_exact) + 1:]
                world = rest.removesuffix(" exactly")
                cells.append([world])
            else:
                raise VerificationError(f"unparsable partition phrase {part!r}")
        partitions[agents[name]] = sorted(cells)
    if set(partitions) != set(agents.values()):
        raise VerificationError(
            f"expected partitions for {sorted(agents.values())}, "
            f"found {sorted(partitions)}"
        )
    return partitions


def _parse_target_scenario(text: str) -> str:
    block = _section(text, "Scenario under evaluation")
    match = re.fullmatch(r"`(w\d+)` \([^)]+\)", block)
    if not match:
        raise VerificationError(f"unparsable target scenario block: {block!r}")
    return match.group(1)


# ---------------------------------------------------------------------------
# Family parsers (task.md -> reconstructed formal state).
# ---------------------------------------------------------------------------

def parse_announcements_task(text: str) -> dict:
    vocab_table = E2_E4_E5_VOCAB
    model_block = _section(text, "The model (common knowledge)")
    vocab = _any_vocab_for(model_block, vocab_table)
    valuation = _parse_world_valuation(model_block, vocab)
    partitions = _parse_partition_lines(
        model_block, vocab, verb_exact="identifies", verb_group="cannot distinguish"
    )
    ann_block = _section(text, "Public announcements (in order)")
    announcements = []
    for number, phrase in re.findall(r"^(\d+)\. It is publicly announced that (.+)\.$",
                                     ann_block, re.M):
        announcements.append(parse_formula(phrase, vocab))
    question = _section(text, "Question")
    marker = "is it the case that "
    if marker not in question:
        raise VerificationError(f"unparsable question: {question!r}")
    query = parse_formula(question.split(marker, 1)[1], vocab)
    return {
        "family": "epistemic_announcements",
        "scenario": _scenario_of(vocab_table, vocab),
        "n_worlds": len(valuation),
        "valuation": valuation,
        "partitions": partitions,
        "announcements": [formula_to_list(a) for a in announcements],
        "query_formula": formula_to_list(query),
    }


def _any_vocab_for(block: str, table: Dict[str, SurfaceVocab]) -> SurfaceVocab:
    for vocab in table.values():
        labels = set(vocab.world_labels)
        if any(f"({label})" in block for label in labels):
            return vocab
    raise VerificationError("no surface vocabulary matches the model block")


def _scenario_of(table: Dict[str, SurfaceVocab], vocab: SurfaceVocab) -> str:
    for name, v in table.items():
        if v is vocab:
            return name
    raise VerificationError("vocabulary not registered")


def parse_nested_knowledge_task(text: str) -> dict:
    vocab = _any_vocab_for(_section(text, "The model (common knowledge)"), E2_E4_E5_VOCAB)
    model_block = _section(text, "The model (common knowledge)")
    valuation = _parse_world_valuation(model_block, vocab)
    partitions = _parse_partition_lines(
        model_block, vocab, verb_exact="identifies", verb_group="cannot distinguish"
    )
    target = _parse_target_scenario(text)
    question = _section(text, "Question")
    tail_match = re.search(r"at scenario `w\d+` \([^)]+\), that (.+)$", question, re.S)
    if not tail_match:
        raise VerificationError(f"unparsable question: {question!r}")
    query = parse_formula(tail_match.group(1), vocab)
    return {
        "family": "epistemic_nested_knowledge",
        "scenario": _scenario_of(E2_E4_E5_VOCAB, vocab),
        "n_worlds": len(valuation),
        "valuation": valuation,
        "partitions": partitions,
        "actual_world": target,
        "query_formula": formula_to_list(query),
    }


def parse_fragmented_observation_task(text: str) -> dict:
    vocab = _any_vocab_for(_section(text, "The model (common knowledge)"), E2_E4_E5_VOCAB)
    model_block = _section(text, "The model (common knowledge)")
    valuation = _parse_world_valuation(model_block, vocab)
    partitions = _parse_partition_lines(
        model_block, vocab, verb_exact="observes", verb_group="cannot distinguish"
    )
    target = _parse_target_scenario(text)
    question = _section(text, "Question")
    marker = ", that "
    if marker not in question:
        raise VerificationError(f"unparsable question: {question!r}")
    tail = question.split(marker, 1)[1]
    query = parse_formula(tail, vocab)
    return {
        "family": "epistemic_fragmented_observation",
        "scenario": _scenario_of(E2_E4_E5_VOCAB, vocab),
        "n_worlds": len(valuation),
        "valuation": valuation,
        "partitions": partitions,
        "actual_world": target,
        "query_formula": formula_to_list(query),
    }


def parse_silence_task(text: str) -> dict:
    setup = _section(text, "The setup (common knowledge)")
    vocab = None
    for candidate in E3_VOCAB.values():
        if all(
            f"- `w{i + 1}`: {label}." in setup
            for i, label in enumerate(candidate.world_labels)
        ):
            vocab = candidate
            break
    if vocab is None:
        raise VerificationError("no E3 surface vocabulary matches the setup block")
    world_labels = {f"w{i + 1}": label for i, label in enumerate(vocab.world_labels)}
    valuation: Dict[str, List[str]] = {}
    for world, label in world_labels.items():
        if f"- `{world}`: {label}." not in setup:
            raise VerificationError(f"missing world line for {world}")
        valuation[world] = []
    prior: Dict[str, str] = {}
    prior_match = re.search(r"^- Prior: (.+)\.$", setup, re.M)
    if not prior_match:
        raise VerificationError("missing prior line")
    for world, value in re.findall(r"P\(`(w\d+)`\) = ([0-9/]+)", prior_match.group(1)):
        prior[world] = value
    announce_sets: Dict[str, List[str]] = {}
    agents = _agent_ids(vocab)
    for name, targets in re.findall(r"^  - ([^:]+) announces exactly in: (.+)\.$", setup, re.M):
        if name not in agents:
            raise VerificationError(f"unknown agent name {name!r}")
        worlds = re.findall(r"`(w\d+)`", targets)
        if not worlds:
            raise VerificationError(f"empty announce set for {name}")
        announce_sets[agents[name]] = sorted(worlds)
    observation_block = _section(text, "Observation")
    if "nobody announced anything (silence)" in observation_block:
        observation = "silence"
    elif "at least one agent announced (a message was made)" in observation_block:
        observation = "message"
    else:
        raise VerificationError(f"unparsable observation block: {observation_block!r}")
    return {
        "family": "epistemic_silence",
        "scenario": _scenario_of(E3_VOCAB, vocab),
        "valuation": valuation,
        "prior_dist": prior,
        "announce_sets": announce_sets,
        "observation": observation,
    }


def parse_type_games_task(text: str) -> dict:
    """Parse the public Bayesian-game description (E6)."""
    game = _section(text, "The game (common knowledge)")
    types_a: List[str] = []
    types_b: List[str] = []
    current = None
    for line in game.splitlines():
        stripped = line.strip()
        if "possible types:" in line:
            current = types_a if "Alice" in line or _first_player_name(text) in line \
                else types_b
            continue
        match = re.match(r"^- `(t\d+)`: ", stripped)
        if match and current is not None and line.startswith("  -"):
            current.append(match.group(1))
    prior: Dict[str, str] = {}
    for ta, tb, value in re.findall(r"P\(`(t\d+)`, `(t\d+)`\) = ([0-9/\-]+)", game):
        prior[f"{ta},{tb}"] = value
    payoffs: Dict[str, Dict[str, List[str]]] = {}
    current_key = None
    for line in game.splitlines():
        key_match = re.match(r"  - types \(`(t\d+)`, `(t\d+)`\):$", line)
        if key_match:
            current_key = f"{key_match.group(1)},{key_match.group(2)}"
            payoffs[current_key] = {}
            continue
        pair_match = re.match(r"    - \(`([XY])`, `([XY])`\): \(([^,]+), ([^)]+)\)$", line)
        if pair_match and current_key is not None:
            ua = Fraction(pair_match.group(3).strip())
            ub = Fraction(pair_match.group(4).strip())
            payoffs[current_key][f"{pair_match.group(1)},{pair_match.group(2)}"] = [
                str(ua), str(ub)
            ]
    if not types_a or not types_b or not prior or not payoffs:
        raise VerificationError("incomplete E6 game description")
    return {
        "family": "epistemic_type_games",
        "types_a": types_a,
        "types_b": types_b,
        "prior": prior,
        "payoff_matrices": payoffs,
    }


def _first_player_name(text: str) -> str:
    match = re.search(r"(\w+) moves simultaneously", text)
    return match.group(1) if match else "Alice"


def _independent_enumerate_bne(types_a: List[str], types_b: List[str],
                               prior: Dict[str, str],
                               payoffs: Dict[str, Dict[str, List[str]]]):
    """Independently written pure-BNE enumerator (oracle independence).

    Deliberately structured differently from the family core: belief tables
    are fractional conditional distributions keyed by both players, and the
    best-response loop iterates candidate deviations for both players in a
    single combined pass.
    """
    actions = ("X", "Y")
    prior_f = {tuple(k.split(",")): Fraction(v) for k, v in prior.items()}
    util = {
        tuple(k.split(",")): {
            tuple(pk.split(",")): (Fraction(u[0]), Fraction(u[1]))
            for pk, u in m.items()
        }
        for k, m in payoffs.items()
    }

    def cond_b(eliciting_player: str, own: str) -> Dict[str, Fraction]:
        others = types_b if eliciting_player == "a" else types_a
        marg = sum(
            (prior_f[(own, o)] if eliciting_player == "a" else prior_f[(o, own)])
            for o in others
        )
        return {
            o: (prior_f[(own, o)] if eliciting_player == "a" else prior_f[(o, own)]) / marg
            for o in others
        }

    beliefs = {
        ("a", ta): cond_b("a", ta) for ta in types_a
    }
    beliefs.update({("b", tb): cond_b("b", tb) for tb in types_b})

    def value(player: str, own: str, act: str, opp_strategy: Dict[str, str]) -> Fraction:
        total = Fraction(0)
        for opp, prob in beliefs[(player, own)].items():
            opp_act = opp_strategy[opp]
            if player == "a":
                ua, ub = util[(own, opp)][(act, opp_act)]
                total += prob * ua
            else:
                ua, ub = util[(opp, own)][(opp_act, act)]
                total += prob * ub
        return total

    profiles_a = [dict(zip(types_a, c)) for c in itertools.product(actions, repeat=len(types_a))]
    profiles_b = [dict(zip(types_b, c)) for c in itertools.product(actions, repeat=len(types_b))]
    out = []
    for sa in profiles_a:
        for sb in profiles_b:
            best = True
            for ta in types_a:
                v = value("a", ta, sa[ta], sb)
                if any(value("a", ta, d, sb) > v for d in actions if d != sa[ta]):
                    best = False
            if best:
                for tb in types_b:
                    v = value("b", tb, sb[tb], sa)
                    if any(value("b", tb, d, sa) > v for d in actions if d != sb[tb]):
                        best = False
            if best:
                out.append({"player_a": dict(sa), "player_b": dict(sb)})
    return out


def v3_verify_type_games(task_md: str, spec: dict) -> dict:
    parsed = PARSERS["epistemic_type_games"](task_md)
    equilibria = _independent_enumerate_bne(
        parsed["types_a"], parsed["types_b"], parsed["prior"],
        parsed["payoff_matrices"]
    )
    if len(equilibria) != 1:
        return {"verified": False,
                "failure_mode": f"expected unique equilibrium, found {len(equilibria)}"}
    ok = equilibria[0] == spec["equilibrium"]
    return {
        "verified": ok,
        "failure_mode": None if ok else "ground_truth_mismatch",
        "equilibrium": equilibria[0],
    }


PARSERS = {
    "epistemic_type_games": parse_type_games_task,
    "epistemic_announcements": parse_announcements_task,
    "epistemic_nested_knowledge": parse_nested_knowledge_task,
    "epistemic_fragmented_observation": parse_fragmented_observation_task,
    "epistemic_silence": parse_silence_task,
}

# Spec fields compared by V1 (formal state + registered proposition only;
# semantic results such as ground truth are deliberately excluded).
V1_FIELDS = {
    "epistemic_type_games": ("types_a", "types_b", "prior", "payoff_matrices"),
    "epistemic_announcements": (
        "valuation", "partitions", "announcements", "query_formula",
    ),
    "epistemic_nested_knowledge": (
        "valuation", "partitions", "actual_world", "query_formula",
    ),
    "epistemic_fragmented_observation": (
        "valuation", "partitions", "actual_world", "query_formula",
    ),
    "epistemic_silence": ("prior_dist", "announce_sets", "observation"),
}


def v1_reconstruct(task_md: str, family: str) -> Tuple[dict, List[str]]:
    """V1: reconstruct registered formal state from the English text alone.

    Returns (reconstruction, mismatches) where mismatches list error types.
    """
    if family not in PARSERS:
        raise VerificationError(f"unknown family {family!r}")
    try:
        parsed = PARSERS[family](task_md)
    except VerificationError as exc:
        return {}, [f"parse_failure: {exc}"]
    return parsed, []


def v1_compare(reconstruction: dict, spec: dict, family: str) -> List[str]:
    mismatches = []
    for field_name in V1_FIELDS[family]:
        expected = spec.get(field_name)
        got = reconstruction.get(field_name)
        if field_name == "partitions":
            expected = {agent: sorted(cells) for agent, cells in expected.items()}
            got = {agent: sorted(cells) for agent, cells in (got or {}).items()}
        if expected != got:
            mismatches.append(f"field_mismatch:{field_name}")
    return mismatches


# ---------------------------------------------------------------------------
# V3: independent ground-truth recomputation (substrate only).
# ---------------------------------------------------------------------------

def _model_from_parsed(parsed: dict) -> PAL.EpistemicModel:
    worlds = frozenset(sorted(parsed["valuation"]))
    partitions = {
        agent: frozenset(frozenset(cell) for cell in cells)
        for agent, cells in parsed["partitions"].items()
    }
    valuation = {w: frozenset(parsed["valuation"][w]) for w in parsed["valuation"]}
    return PAL.EpistemicModel(worlds, partitions, valuation)


def _eval(struct: Struct) -> PAL.Formula:
    if struct[0] == "atom":
        return PAL.atom(struct[1])
    if struct[0] == "neg":
        return PAL.neg(_eval(struct[1]))
    if struct[0] == "knows":
        return PAL.knows(struct[1], _eval(struct[2]))
    if struct[0] == "joint_entails":
        return _eval(struct[1])
    raise VerificationError(f"unknown structure {struct!r}")


def v3_verify_announcements(task_md: str, spec: dict) -> dict:
    parsed = PARSERS["epistemic_announcements"](task_md)
    model = _model_from_parsed(parsed)
    for step, announcement in enumerate(parsed["announcements"]):
        model = PAL.public_announce(model, _eval(tuple(announcement)))
        if not model.worlds:
            raise VerificationError(f"announcement {step} empties the model")
    query = _eval(tuple(parsed["query_formula"]))
    truths = {bool(query(model, w)) for w in model.worlds}
    if len(truths) != 1:
        return {
            "verified": False,
            "failure_mode": "not_publicly_derivable",
            "ground_truth": None,
        }
    truth = next(iter(truths))
    return {
        "verified": truth == spec["ground_truth"],
        "failure_mode": None if truth == spec["ground_truth"] else "ground_truth_mismatch",
        "ground_truth": truth,
    }


def v3_verify_nested_knowledge(task_md: str, spec: dict) -> dict:
    parsed = PARSERS["epistemic_nested_knowledge"](task_md)
    model = _model_from_parsed(parsed)
    truth = bool(_eval(tuple(parsed["query_formula"]))(model, parsed["actual_world"]))
    return {
        "verified": truth == spec["ground_truth"],
        "failure_mode": None if truth == spec["ground_truth"] else "ground_truth_mismatch",
        "ground_truth": truth,
    }


def v3_verify_fragmented_observation(task_md: str, spec: dict) -> dict:
    parsed = PARSERS["epistemic_fragmented_observation"](task_md)
    model = _model_from_parsed(parsed)
    joint = CSO.joint_information(model, sorted(model.partitions), parsed["actual_world"])
    query = tuple(parsed["query_formula"])
    payload = query[1] if query[0] == "neg" else query
    inner = _eval(payload)
    truth = all(bool(inner(model, w)) for w in sorted(joint))
    if query[0] == "neg":
        truth = not truth
    return {
        "verified": truth == spec["ground_truth"],
        "failure_mode": None if truth == spec["ground_truth"] else "ground_truth_mismatch",
        "ground_truth": truth,
    }


def v3_verify_silence(task_md: str, spec: dict) -> dict:
    parsed = PARSERS["epistemic_silence"](task_md)
    prior = {w: Fraction(v) for w, v in parsed["prior_dist"].items()}
    protocol = {}
    for agent, announce_set in parsed["announce_sets"].items():
        members = frozenset(announce_set)
        protocol[agent] = (lambda world, _m=members: world in _m)
    table = {}
    for world in prior:
        lam = SILENCE.silence_event_likelihood(world, protocol)
        table[world] = {"silence": lam, "announcement": Fraction(1) - lam}
    realized = "silence" if parsed["observation"] == "silence" else "announcement"
    posterior = POLICY.bayes_update(
        POLICY.SuppliedPolicyInstance(prior=prior, policy=table,
                                      realized_observation=realized)
    )
    posterior_world1 = posterior["w1"]
    prior_world1 = prior["w1"]
    direction = (
        "unchanged" if posterior_world1 == prior_world1
        else "increased" if posterior_world1 > prior_world1 else "decreased"
    )
    ok = (
        posterior_world1 == Fraction(spec["posterior_world1"])
        and direction == spec["direction"]
    )
    return {
        "verified": ok,
        "failure_mode": None if ok else "ground_truth_mismatch",
        "posterior_world1": str(posterior_world1),
        "direction": direction,
    }


V3_VERIFIERS = {
    "epistemic_type_games": v3_verify_type_games,
    "epistemic_announcements": v3_verify_announcements,
    "epistemic_nested_knowledge": v3_verify_nested_knowledge,
    "epistemic_fragmented_observation": v3_verify_fragmented_observation,
    "epistemic_silence": v3_verify_silence,
}


def v3_verify(task_md: str, spec: dict, family: str) -> dict:
    if family not in V3_VERIFIERS:
        raise VerificationError(f"unknown family {family!r}")
    return V3_VERIFIERS[family](task_md, spec)


# ---------------------------------------------------------------------------
# CLI: verify a generated environment directory.
# ---------------------------------------------------------------------------

def verify_generated_dir(generated_dir: Path, modes: Tuple[str, ...]) -> dict:
    task_path = generated_dir / "agent" / "workspace" / "task.md"
    spec_path = generated_dir / "judge" / "instance_spec.py"
    if not task_path.is_file() or not spec_path.is_file():
        raise VerificationError(
            f"{generated_dir} is missing task.md or instance_spec.py"
        )
    tree = ast.parse(spec_path.read_text(encoding="utf-8"))
    spec = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "INSTANCE_SPEC":
            spec = ast.literal_eval(node.value)
    if spec is None:
        raise VerificationError("INSTANCE_SPEC not found in instance_spec.py")
    family = spec["family"]
    task_md = task_path.read_text(encoding="utf-8")
    report = {"dir": str(generated_dir), "family": family}
    if "v1" in modes:
        reconstruction, errors = v1_reconstruct(task_md, family)
        mismatches = errors or v1_compare(reconstruction, spec, family)
        report["v1"] = {"exact_reconstruction": not mismatches, "mismatches": mismatches}
    if "v3" in modes:
        try:
            report["v3"] = v3_verify(task_md, spec, family)
        except (VerificationError, SpecError, ValueError) as exc:
            report["v3"] = {
                "verified": False,
                "failure_mode": f"verification_error: {exc}",
            }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", action="append", required=True,
                        help="generated environment directory (repeatable)")
    parser.add_argument("--mode", choices=("v1", "v3", "both"), default="both")
    args = parser.parse_args(argv)
    modes = ("v1", "v3") if args.mode == "both" else (args.mode,)
    failed = False
    for directory in args.dir:
        report = verify_generated_dir(Path(directory), modes)
        ok = all(
            report.get(section, {}).get("exact_reconstruction", False)
            if section == "v1"
            else report.get(section, {}).get("verified", False)
            for section in modes
        )
        failed = failed or not ok
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
