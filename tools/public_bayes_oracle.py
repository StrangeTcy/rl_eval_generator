#!/usr/bin/env python3
"""Public-only Bayes oracle for epistemic_games.

Takes ONLY the rendered task.md text as input, extracts prior, behavior
tables, and observation via regex/parsing, and computes posterior with Bayes'
rule. Does NOT import the generator's grading helpers.

This verifies that the task contains all necessary public information.

Usage:
    python tools/public_bayes_oracle.py path/to/task.md
    python tools/public_bayes_oracle.py --self-test
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, Tuple


def _extract_prior(task_md: str) -> float:
    # P(world 1) = 0.50, P(world 2) = 0.50  or  P(world 1) = 0.60
    m = re.search(r"P\(world 1\)\s*=\s*([0-9]*\.?[0-9]+)", task_md)
    if not m:
        raise ValueError("Could not find P(world 1) in task.md")
    return float(m.group(1))


def _extract_observation(task_md: str) -> Tuple[str, str]:
    """Return (observation_id, observation_text).

    observation_id is 'denial' or 'vague' if explicitly given (bare_table),
    otherwise inferred from text.
    observation_text is the raw transcript text.
    """
    # Bare-table: Observation: denial
    m = re.search(r"Observation:\s*(denial|vague)", task_md)
    if m:
        obs_id = m.group(1)
        # Also try to get observed text
        m2 = re.search(r'You observed:\s*"([^"]+)"', task_md)
        obs_text = m2.group(1) if m2 else obs_id
        return obs_id, obs_text

    # Narrative: You observed: X said: "text"  or You observed: "text"
    m = re.search(r'You observed:.*said:\s*"([^"]+)"', task_md)
    if not m:
        m = re.search(r'You observed:\s*"([^"]+)"', task_md)
    if not m:
        raise ValueError("Could not find observed transcript in task.md")
    obs_text = m.group(1)
    # obs_id unknown yet, will be inferred from behavior tables
    return "", obs_text


def _parse_behavior_line(line: str) -> Tuple[str, float]:
    """Parse a line like \"  'text' with probability 0.88\" -> (text, prob)."""
    if "with probability" not in line:
        raise ValueError(f"Not a behavior line: {line!r}")
    left, right = line.split("with probability", 1)
    left = left.strip()
    right = right.strip()
    # left should be a quoted string literal, e.g. 'UP - no issue found.'
    # Use literal_eval to unescape
    try:
        action_text = ast.literal_eval(left)
    except Exception:
        # Fallback: strip surrounding quotes
        action_text = left.strip("'\"")
    try:
        prob = float(right.split()[0])
    except Exception as exc:
        raise ValueError(f"Could not parse probability from {line!r}: {exc}") from exc
    return action_text, prob


def _extract_behavior_tables(task_md: str) -> Dict[str, Dict[str, float]]:
    """Extract behavior tables for world1 and world2.

    Returns dict world_id -> {action_text -> prob} and also
    {action_id -> prob} for bare_table.
    For narrative, we get action_text mapping; for bare_table we get
    P(denial)/P(vague) directly.
    """
    # Try bare_table format first
    bare_w1 = re.search(r"World1:\s*P\(denial\)=([0-9.]+),\s*P\(vague\)=([0-9.]+)", task_md)
    bare_w2 = re.search(r"World2:\s*P\(denial\)=([0-9.]+),\s*P\(vague\)=([0-9.]+)", task_md)
    if bare_w1 and bare_w2:
        return {
            "world1": {"denial": float(bare_w1.group(1)), "vague": float(bare_w1.group(2))},
            "world2": {"denial": float(bare_w2.group(1)), "vague": float(bare_w2.group(2))},
        }

    # Narrative format: split by world markers
    # Markers: ## World 1, ## World 2, ## Hypothesis 1, ## Hypothesis 2
    world_sections = {}
    # Find all world headings and their start indices
    pattern = re.compile(r"##\s*(?:World|Hypothesis)\s*([12])", re.IGNORECASE)
    matches = list(pattern.finditer(task_md))
    for i, match in enumerate(matches):
        world_num = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(task_md)
        section = task_md[start:end]
        world_id = f"world{world_num}"
        # In that section, find lines with "with probability"
        table: Dict[str, float] = {}
        for line in section.splitlines():
            if "with probability" in line:
                try:
                    act_text, prob = _parse_behavior_line(line)
                    table[act_text] = prob
                except ValueError:
                    continue
        if table:
            world_sections[world_id] = table

    if world_sections:
        return world_sections

    # Fallback: global search for probability lines (should be 4 lines total)
    prob_lines = [ln for ln in task_md.splitlines() if "with probability" in ln]
    if len(prob_lines) >= 4:
        # Assume first 2 are world1, next 2 world2 (order in template)
        w1: Dict[str, float] = {}
        w2: Dict[str, float] = {}
        for j, line in enumerate(prob_lines[:2]):
            act, prob = _parse_behavior_line(line)
            w1[act] = prob
        for line in prob_lines[2:4]:
            act, prob = _parse_behavior_line(line)
            w2[act] = prob
        return {"world1": w1, "world2": w2}

    raise ValueError("Could not extract behavior tables from task.md")


def _extract_likelihoods_from_bare_table(task_md: str) -> Tuple[float, float] | None:
    m = re.search(
        r"Likelihoods:\s*L1=P\(observed\|world1\)=([0-9.]+),\s*L2=P\(observed\|world2\)=([0-9.]+)",
        task_md,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def solve_task_md(task_md: str) -> Dict[str, object]:
    """Public-only solver: parse task.md text, compute posterior, verdict, support."""
    pi1 = _extract_prior(task_md)
    obs_id, obs_text = _extract_observation(task_md)
    behavior = _extract_behavior_tables(task_md)

    # Determine likelihoods
    l1 = l2 = None

    # If bare_table includes explicit likelihoods, use those directly (most robust)
    bare_likelihoods = _extract_likelihoods_from_bare_table(task_md)
    if bare_likelihoods is not None:
        l1, l2 = bare_likelihoods
    else:
        # Try to get likelihoods from behavior tables
        # behavior dict may be keyed by action_id (denial/vague) or action_text
        for world_id in ("world1", "world2"):
            table = behavior.get(world_id, {})
            # If table keyed by action_id and we have obs_id
            if obs_id and obs_id in table:
                prob = table[obs_id]
                if world_id == "world1":
                    l1 = prob
                else:
                    l2 = prob
            else:
                # Try to match by observation text
                # Exact match
                if obs_text in table:
                    prob = table[obs_text]
                else:
                    # Substring match (observation text may be inside quoted text)
                    prob = None
                    for act_text, p in table.items():
                        if obs_text in act_text or act_text in obs_text:
                            prob = p
                            break
                    if prob is None:
                        # Fallback: if table has 2 entries, and observation is denial/vague,
                        # try to infer from action_text content
                        # For narrative, denial text often contains "didn't notice" or "UP"
                        # vague contains "don't want" or "pull logs"
                        # We can attempt to guess, but better to fail
                        raise ValueError(
                            f"Could not find likelihood for observation {obs_text!r} in {world_id} table {table}"
                        )
                if world_id == "world1":
                    l1 = prob
                else:
                    l2 = prob

    if l1 is None or l2 is None:
        raise ValueError(f"Could not determine likelihoods: L1={l1}, L2={l2}")

    # Bayes
    denom = l1 * pi1 + l2 * (1 - pi1)
    posterior = (l1 * pi1 / denom) if denom != 0 else 0.5

    # Verdict from likelihood ratio
    if min(l1, l2) <= 0:
        ratio = float("inf") if max(l1, l2) > 0 else 1.0
    else:
        ratio = max(l1 / l2, l2 / l1)

    if ratio == 1.0:
        verdict = "indistinguishable"
    elif ratio < 3:
        verdict = "weakly_distinguishable"
    else:
        verdict = "distinguishable"

    if posterior > 0.5:
        support = "world1"
    elif posterior < 0.5:
        support = "world2"
    else:
        support = "neither"

    return {
        "prior_world1": pi1,
        "observation_id": obs_id,
        "observation_text": obs_text,
        "likelihoods": {"world1": l1, "world2": l2},
        "likelihood_ratio": ratio,
        "posterior_world1": posterior,
        "verdict": verdict,
        "most_supported": support,
        "behavior_tables": behavior,
    }


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        # Quick self-test on generated instances
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "envs" / "epistemic_games" / "files"))
        import core

        for framing in ("narrative", "bare_table"):
            for seed in range(5):
                inst = core.build_instance("trap", "weak", "balanced", "paired", seed, framing=framing)
                task_md = inst.public_task_md()
                solved = solve_task_md(task_md)
                true_post = float(inst.posterior1)
                err = abs(solved["posterior_world1"] - true_post)
                assert err < 0.015, f"framing={framing} seed={seed} err={err} solved={solved['posterior_world1']} true={true_post}"
                assert solved["verdict"] == inst.verdict, f"verdict mismatch {solved['verdict']} vs {inst.verdict}"
                assert solved["most_supported"] == inst.most_supported
        print("self-test passed: public_bayes_oracle matches generator on narrative and bare_table")
        return

    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} path/to/task.md  or  {sys.argv[0]} --self-test")
        sys.exit(1)

    task_path = Path(sys.argv[1])
    task_md = task_path.read_text(encoding="utf-8")
    result = solve_task_md(task_md)
    print(f"Prior world1: {result['prior_world1']}")
    print(f"Observation: {result['observation_id'] or result['observation_text']}")
    print(f"Likelihoods: L1={result['likelihoods']['world1']:.4f} L2={result['likelihoods']['world2']:.4f} R={result['likelihood_ratio']:.4f}")
    print(f"Posterior world1: {result['posterior_world1']:.6f}")
    print(f"Verdict: {result['verdict']}")
    print(f"Most supported: {result['most_supported']}")


if __name__ == "__main__":
    main()
