#!/usr/bin/env python3
"""Offline evaluator for private trajectory case and answer JSONL records.

The image intentionally has no network client and accepts no provider settings.
It scores exact behavioral answers and emits diagnostic stale-witness matches;
those matches are never converted into partial credit.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def normalize(value: Any) -> str:
    text = str(value or "").strip()
    final = re.search(r"(?:^|\n)FINAL\s*:\s*(.+)$", text, flags=re.I | re.S)
    if final:
        text = final.group(1).strip()
    if "\n" in text:
        text = text.splitlines()[-1].strip()
    text = text.strip(" .`\"'")
    return re.sub(r"\s+", "", text).lower()


def format_valid(case: dict[str, Any], answer: str) -> bool:
    query = case.get("query_type")
    if query == "parse_only":
        return answer in {
            "same",
            "flip",
            "0",
            "1",
            normalize(case.get("initial_state", {}).get("payload")),
        }
    if query in {"template_at_T", "complete_return"}:
        return answer in {"yes", "no"}
    return bool(re.fullmatch(r"[^()]+\([^()]+\)", answer))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: record must be an object")
        records.append(value)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Score private trajectory JSONL records offline.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = {str(record["case_id"]): record for record in read_jsonl(args.cases)}
    answers = read_jsonl(args.answers)
    results: list[dict[str, Any]] = []
    for answer_record in answers:
        case_id = str(answer_record.get("case_id", ""))
        case = cases.get(case_id)
        if case is None:
            results.append({"case_id": case_id, "error": "unknown_case", "correct": False})
            continue
        parsed = normalize(answer_record.get("raw_model_output", answer_record.get("answer", "")))
        expected = normalize(case.get("expected_answer", ""))
        correct = parsed == expected
        stale = case.get("stale_witness_prediction")
        results.append(
            {
                "case_id": case_id,
                "api_replication": answer_record.get("api_replication"),
                "parsed_answer": parsed,
                "expected_answer": expected,
                "format_valid": format_valid(case, parsed),
                "correct": correct,
                "matched_stale_witness_prediction": (
                    stale is not None and parsed == normalize(stale) and not correct
                ),
                "witness_status_for_query": case.get("witness_status_for_query"),
                "query_type": case.get("query_type"),
                "horizon": case.get("horizon"),
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    correct = sum(bool(result.get("correct")) for result in results)
    summary = {
        "total_answers": len(results),
        "correct": correct,
        "accuracy": correct / max(1, len(results)),
        "stale_witness_matches": sum(
            bool(result.get("matched_stale_witness_prediction")) for result in results
        ),
        "interpretation": "Exact behavioral score; stale-witness matches are diagnostic only.",
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
