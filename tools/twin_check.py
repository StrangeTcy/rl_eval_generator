#!/usr/bin/env python3
"""Decide whether a generated twin is the experiment its declaration claims.

Three claims are checked, all of them model-free and torch-free, because the thing
being verified here is *generation*, not agent behavior:

* ``semantically_equivalent`` - the two trees must be identical once every value the
  intervention introduced is mapped back.  A twin that differs beyond the declared
  renaming is not a presentation change; it is a different task that has been
  mislabeled, and every invariance result computed from it would be wrong.
* ``observation_changing`` / ``task_changing`` - the trees must differ.  An overlay
  that changes nothing is a config bug, and it is indistinguishable from an agent
  that correctly ignored the intervention.
* ``evaluator_changing`` - the agent-visible tree must be identical and the judge
  tree must differ.  Anything else means the measurement change leaked into the
  workspace, which turns "the model gamed the evaluator" into "the model read it".

Both trees are normalized symmetrically (base value and twin value both map to a
neutral marker), so a real difference cannot be erased by rewriting only one side.

Usage:
    python tools/twin_check.py generated_base generated_twin [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_env as ge  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402



# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def snapshot(directory: Path) -> dict[str, str]:
    """Raw relpath -> sha256(content), manifest excluded. Used for the inert check."""
    out: dict[str, str] = {}
    for rel in gm.iter_files(directory):
        path = directory / rel
        if path.is_symlink():
            raise ValueError(f"symlink in generated tree: {path}")
        data = path.read_bytes()
        out[rel] = gm.sha256_bytes(data)
    return out


# Identifier-like values are matched with lookaround guards; anything else (a file
# name, an instance label) is matched literally, since those characters already
# separate it from surrounding text.
_ATOMIC = re.compile(r"[A-Za-z0-9_]+")
_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/+=+-]*")


def _value_pattern(value: str) -> re.Pattern[str]:
    """Match an injected value without eating neighbouring identifier characters.

    ``q`` must not match inside ``queue``, and ``moco_model`` must not match inside
    ``moco_model_extra``; a multi-line block value needs no guard at all.
    """
    escaped = re.escape(value)
    if _ATOMIC.fullmatch(value):
        return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])")
    return re.compile(escaped)


_NAME_LIKE = _TOKEN


def is_name_like(value: str) -> bool:
    """A value is name-like when it is one atomic token: an identifier, file name,
    or instance label.

    Only name-like values can be normalized *invertibly*: an overlay that replaces
    "MoCo" with "RetrievalPooledEncoder" moved a name, while one that replaces a
    rendered task text or a whole test body moved content. Content-valued overlays
    cannot be argued back into equality without rewriting whole files, so a
    semantically-equivalent claim built from them is reported as unprovable rather
    than as a pass.
    """
    if not value or "\n" in value or "\t" in value:
        return False
    stripped = value.strip()
    return len(stripped) <= 128 and bool(_NAME_LIKE.fullmatch(stripped))


def _twin_to_base(pairs: dict[str, tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    """Ordered (pattern, base value) rewrites that map twin text back onto base text."""
    name_like = {
        name: (base, twin)
        for name, (base, twin) in pairs.items()
        if is_name_like(twin) and is_name_like(base)
    }
    # Longest twin value first, so "moco_model.py" is mapped before "moco_model".
    ordered = sorted(name_like.items(), key=lambda item: len(item[1][1]), reverse=True)
    return [(_value_pattern(twin), base) for _, (base, twin) in ordered]


def blocked_keys(pairs: dict[str, tuple[str, str]], rewrites: list[tuple[re.Pattern[str], str]]) -> list[str]:
    """Differing placeholders the normalization cannot account for.

    A non-name-like value is fine when applying the name-like rewrites to it
    reproduces the base value exactly - that is a composed constant such as
    PATCHABLE_FILES, which follows from the file name it embeds. Values that do not
    follow (a rendered task text that branches on the overlay) are reported instead
    of being quietly rewritten, and they downgrade the verdict to ``unverified``.
    """
    name_like = {
        name: (base, twin)
        for name, (base, twin) in pairs.items()
        if is_name_like(twin) and is_name_like(base)
    }
    blocked: list[str] = []
    for name, (base, twin) in sorted(pairs.items()):
        if name in name_like:
            continue
        mapped = twin
        for pattern, replacement in rewrites:
            mapped = pattern.sub(lambda _m: replacement, mapped)
        if mapped != base:
            blocked.append(name)
    return blocked


def normalize_twin(directory: Path, rewrites: list[tuple[re.Pattern[str], str]]) -> dict[str, str]:
    """Snapshot of ``directory`` with every overlay-introduced value mapped back.

    File *paths* are mapped too, because an overlay may rename the module file
    itself; a rename that is not invertible is an error rather than a difference.
    """
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for rel in gm.iter_files(directory):
        path = directory / rel
        if path.is_symlink():
            raise ValueError(f"symlink in generated tree: {path}")
        text = _read_text(path)
        if text is None:
            normalized_rel, digest = rel, gm.sha256_bytes(path.read_bytes())
        else:
            normalized_rel = rel
            for pattern, replacement in rewrites:
                normalized_rel = pattern.sub(lambda _m, value=replacement: value, normalized_rel)
                text = pattern.sub(lambda _m, value=replacement: value, text)
            digest = gm.sha256_text(text)
        if normalized_rel in seen and seen[normalized_rel] != digest:
            raise ValueError(
                f"the declared renaming is not invertible in {directory}: two distinct "
                f"files normalize to '{normalized_rel}' with different content"
            )
        seen[normalized_rel] = digest
        out[normalized_rel] = digest
    return out


def _alias_map(manifest: dict[str, Any]) -> dict[str, str]:
    """alias -> token, for rename-mechanism overlays recorded in a manifest."""
    aliases: dict[str, str] = {}
    for overlay in manifest.get("interventions") or []:
        for token, info in (overlay.get("renames") or {}).items():
            alias = str(info.get("alias") or "")
            if alias:
                aliases[alias] = token
    return aliases


def substitution_pairs(
    env: str,
    base_manifest: dict[str, Any],
    twin_manifest: dict[str, Any],
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Recompute both substitution tables and report what the overlays changed.

    Going through ``generate_env.prepare_generation`` rather than diffing text
    afterwards is what makes the verdict mean something: it is the same resolution
    order (axes, then overlays, then constants, then the renderer hook, then
    recursive resolution) that produced the two trees, including the values that are
    only visible after composition.
    """
    base_levels = dict(base_manifest.get("difficulty_vector") or {})
    twin_levels = dict(twin_manifest.get("difficulty_vector") or {})
    twin_ids = [str(item.get("id")) for item in twin_manifest.get("interventions") or []]
    base_ids = [str(item.get("id")) for item in base_manifest.get("interventions") or []]

    base = ge.prepare_generation(
        env, str(base_manifest.get("output_name") or "twin_base"), base_levels,
        seed=int(base_manifest.get("seed", 0)), interventions=base_ids,
    )["subs"]
    twin = ge.prepare_generation(
        env, str(twin_manifest.get("output_name") or "twin_member"), twin_levels,
        seed=int(twin_manifest.get("seed", 0)), interventions=twin_ids,
    )["subs"]

    keys = set(base) | set(twin)
    pairs: dict[str, tuple[str, str]] = {}
    unnormalizable: list[str] = []
    for key in sorted(keys):
        base_value, twin_value = base.get(key, ""), twin.get(key, "")
        if base_value == twin_value:
            continue
        if not base_value.strip() or not twin_value.strip():
            # Nothing to anchor a symmetric replacement to: an inserted or deleted
            # block cannot be mapped back by substitution.
            unnormalizable.append(key)
            continue
        pairs[key] = (base_value, twin_value)
    return pairs, unnormalizable


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

def _subtree(tree: dict[str, str], prefix: str) -> dict[str, str]:
    return {
        key: value for key, value in tree.items()
        if key == prefix or key.startswith(prefix.rstrip("/") + "/")
    }


def compare(base_dir: Path, twin_dir: Path) -> dict[str, Any]:
    base_manifest = gm.read_manifest(base_dir)
    twin_manifest = gm.read_manifest(twin_dir)

    report: dict[str, Any] = {
        "base_generation_id": base_manifest.get("generation_id"),
        "twin_generation_id": twin_manifest.get("generation_id"),
        "pair_id_base": base_manifest.get("pair_id"),
        "pair_id_twin": twin_manifest.get("pair_id"),
        "pair_id_basis": twin_manifest.get("pair_id_basis"),
        "environment": twin_manifest.get("environment"),
        "notes": [],
        "checks": {},
    }

    problems: list[str] = []
    if base_manifest.get("environment") != twin_manifest.get("environment"):
        return {
            **report,
            "status": "fail",
            "equivalence": None,
            "problems": ["twins are not members of the same environment"],
        }
    env = str(twin_manifest.get("environment"))

    interventions = list(twin_manifest.get("interventions") or [])
    if not interventions:
        return {
            **report,
            "status": "fail",
            "equivalence": None,
            "problems": ["twin declares no interventions; there is nothing to compare"],
        }

    equivalences = sorted({str(item.get("equivalence") or "") for item in interventions})
    equivalence = equivalences[0] if len(equivalences) == 1 else "mixed"
    report["equivalence"] = equivalence
    report["proof"] = sorted({str(item.get("proof") or "unverified") for item in interventions})

    pairs, unnormalizable = substitution_pairs(env, base_manifest, twin_manifest)
    renames_twin = _alias_map(twin_manifest)
    renames_base = _alias_map(base_manifest)

    rewrites = _twin_to_base(pairs)
    # Rename-mechanism aliases are exact and always invertible, so they extend the
    # rewrite set directly (alias -> original identifier).
    for alias, token in sorted(renames_twin.items(), key=lambda item: len(item[0]), reverse=True):
        rewrites.append((_value_pattern(alias), token))

    blocked = blocked_keys(pairs, rewrites)

    report["substitutions_changed"] = len(pairs)
    report["normalizable_placeholders"] = sorted(
        name for name in pairs if name not in blocked and name not in unnormalizable
    )
    report["blocked_placeholders"] = blocked
    report["unnormalizable_placeholders"] = unnormalizable
    report["aliases"] = sorted({alias for alias, _ in renames_twin.items()})

    # "Did the overlay fire?" is a narrower question than "do the trees differ?", and
    # the difference matters: two directories always differ in the instance label, so
    # answering it from the file diff would let that label masquerade as an
    # intervention.  What has to have moved is a value this overlay actually sets -
    # a substitution key, a rename with real occurrences, or a layout override.
    declared_keys: set[str] = set()
    layout_declared = False
    for item in interventions:
        for key in (item.get("substitutions") or {}):
            declared_keys.add(gm.strip_placeholders(str(key)))
        if item.get("layout"):
            layout_declared = True
    # `pairs` holds the differing placeholders that normalization can anchor; the ones
    # it cannot (an inserted or deleted block) are in `unnormalizable`.  Both count as
    # the overlay having fired - only the second kind is not textually provable.
    differing = set(pairs) | set(unnormalizable)
    fired_substitutions = sorted(name for name in differing if name in declared_keys)
    fired_renames = sorted(
        str(name)
        for item in interventions
        if str(item.get("mechanism")) == "rename"
        for name, info in (item.get("renames") or {}).items()
        if int((info or {}).get("occurrences") or 0) > 0
    )
    report["overlay_fired"] = {
        "substitutions": fired_substitutions,
        "renames": fired_renames,
        "layout_overridden": layout_declared,
    }
    report["checks"]["overlay_fired"] = bool(
        fired_substitutions or fired_renames or layout_declared
    )

    raw_base = snapshot(base_dir)
    raw_twin = snapshot(twin_dir)
    norm_base = raw_base
    norm_twin = normalize_twin(twin_dir, rewrites)

    report["files_only_in_base"] = sorted(set(raw_base) - set(raw_twin))
    report["files_only_in_twin"] = sorted(set(raw_twin) - set(raw_base))
    report["differing_files_raw"] = sorted(
        key for key in set(raw_base) & set(raw_twin) if raw_base[key] != raw_twin[key]
    )
    report["differing_files_normalized"] = sorted(
        key for key in set(norm_base) & set(norm_twin) if norm_base[key] != norm_twin[key]
    )

    # Two directories always differ in one place: the instance label baked into
    # run_eval.sh, the Dockerfile and the image names.  "Nothing happened" therefore
    # has to mean "nothing happened beyond that label", which is a statement about the
    # normalized trees, not the raw ones.
    raw_equal = raw_base == raw_twin
    normalized_equal = norm_base == norm_twin
    report["checks"]["only_the_instance_label_differs"] = normalized_equal
    if raw_equal:
        report["notes"].append(
            "the twin is byte-identical to its base including the instance label, which "
            "means the two members were generated into the same directory"
        )

    if equivalence == "semantically_equivalent":
        if blocked or unnormalizable:
            report["status"] = "unverified"
            report["notes"].append(
                "this twin changes values that cannot be mapped back invertibly ("
                + ", ".join(sorted(set(blocked) | set(unnormalizable)))
                + "); textual invariance is therefore not established, and the family "
                  "manifest records the expectation as unfalsified rather than satisfied"
            )
        elif normalized_equal:
            report["checks"]["normalized_trees_identical"] = True
            if not report["checks"]["overlay_fired"]:
                report["status"] = "fail"
                report["problems"] = problems + [
                    "the declared renaming changed nothing at this difficulty vector, so "
                    "the two members are one instance: the invariance would be vacuous "
                    "rather than uninformative"
                ]
                return report
            report["status"] = "pass"
        else:
            report["checks"]["normalized_trees_identical"] = False
            report["status"] = "fail"
            report["problems"] = problems + [
                "trees differ beyond the declared renaming: "
                + ", ".join(
                    (report["differing_files_normalized"]
                     + report["files_only_in_base"]
                     + report["files_only_in_twin"])[:8]
                )
            ]
            return report
    elif equivalence in ("observation_changing", "task_changing"):
        report["checks"]["normalized_trees_differ"] = not normalized_equal
        if not report["checks"]["overlay_fired"]:
            report["problems"] = problems + [
                "the overlay sets no value that differs at this difficulty vector: the "
                "twin is its base, so there is no experiment to run. This is a config "
                "bug, not an invariance result"
            ]
            report["status"] = "fail"
            return report
        if normalized_equal:
            report["problems"] = problems + [
                "declared as changing what the agent can observe, but once the instance "
                "label is normalized away the two trees are identical: the overlay fired "
                "nothing at this difficulty vector, so there is no experiment to run. "
                "This is a config bug, not an invariance result"
            ]
            report["status"] = "fail"
            return report
        if equivalence == "task_changing":
            identity_moved = base_manifest.get("pair_id") != twin_manifest.get("pair_id")
            report["checks"]["pair_id_moved"] = identity_moved
            if twin_manifest.get("pair_id_basis") == "latent_spec" and not identity_moved:
                report["problems"] = problems + [
                    "task_changing overlay left pair_id unchanged: the declared task "
                    "change is not visible in the latent spec, so the twin is a "
                    "presentation change with the wrong label"
                ]
                report["status"] = "fail"
                return report
            elif twin_manifest.get("pair_id_basis") != "latent_spec":
                report["notes"].append(
                    "pair_id falls back to the base case id for this environment (no "
                    "latent spec yet), so task-changing status is taken from the "
                    "declaration rather than proved from structure"
                )
        report["status"] = "fail" if problems else "pass"
    elif equivalence == "evaluator_changing":
        agent_same = _subtree(norm_base, "agent") == _subtree(norm_twin, "agent")
        judge_differs = _subtree(raw_base, "judge") != _subtree(raw_twin, "judge")
        report["checks"]["agent_tree_unchanged"] = agent_same
        report["checks"]["judge_tree_changed"] = judge_differs
        if not agent_same:
            problems.append(
                "measurement change leaked into the agent-visible tree; the submission "
                "would be able to read the evaluator it is being measured by"
            )
        if not judge_differs:
            problems.append("judge tree is identical: the substituted evaluator did not take effect")
        report["status"] = "pass" if agent_same and judge_differs and not problems else "fail"
    else:
        report["status"] = "unverified"
        report["notes"].append(
            "mixed equivalence classes in one twin ("
            + ", ".join(equivalences)
            + "): compare one intervention at a time, or the verdict is not attributable"
        )

    report["problems"] = problems
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", type=Path, help="generated base member directory")
    parser.add_argument("twin", type=Path, help="generated twin member directory")
    parser.add_argument("--json", type=Path, default=None, help="write the report here")
    parser.add_argument("-v", "--verbose", action="store_true", help="print the full report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = compare(args.base, args.twin)
    except (FileNotFoundError, ValueError) as exc:
        print(f"twin_check: error: {exc}", file=sys.stderr)
        return 2

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    status = report["status"]
    print(
        f"twin_check: {status.upper()}: {report.get('environment')} "
        f"[{report.get('equivalence')}] "
        f"base={report.get('base_generation_id')} twin={report.get('twin_generation_id')}"
    )
    for problem in report.get("problems", []):
        print(f"  - {problem}")
    for note in report.get("notes", []):
        print(f"  note: {note}")
    if args.verbose:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
