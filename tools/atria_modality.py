"""Provider-modality inventory for selected covering-campaign cases.

This is intentionally conservative. It inspects the selected environment
configuration and layout rather than converting or dropping anything. A word
such as "image" in generated source is recorded as an internal computation;
an actual non-text input path is checked against the provider's declared
modalities and marked unsupported explicitly when it is not served.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.suite_inventory import _load_yaml

NON_TEXT_SUFFIXES = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".wav",
    ".webp",
}
NON_TEXT_WORDS = {
    "audio",
    "image",
    "images",
    "pdf",
    "video",
}


def _path_suffix(path: str) -> str:
    return Path(path).suffix.lower()


def _layout_paths(config: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    layout = config.get("layout", {})
    if isinstance(layout, dict):
        for destination, source in layout.items():
            if isinstance(destination, str):
                paths.append(destination)
            if isinstance(source, str):
                paths.append(source)
    static_files = config.get("static_files", [])
    if isinstance(static_files, list):
        for item in static_files:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict):
                for key, value in item.items():
                    if isinstance(key, str):
                        paths.append(key)
                    if isinstance(value, str):
                        paths.append(value)
    return paths


def inventory_selected_modalities(
    manifest: dict[str, Any],
    *,
    root: Path,
    provider: str = "atria",
    model: str | None = None,
    input_modalities: list[str] | tuple[str, ...] = ("text",),
) -> dict[str, Any]:
    """Return a provider-specific compatibility record for every selected case.

    The legacy Atria fields remain in the default Atria report for consumers
    of the original pilot; generalized campaign consumers should use
    ``unsupported_for_provider`` and
    ``all_selected_cases_provider_modality_compatible``.
    """

    root = root.resolve()
    modalities = {str(item).lower() for item in input_modalities}
    extension_modality = {
        ".bmp": "image", ".gif": "image", ".jpeg": "image", ".jpg": "image",
        ".png": "image", ".webp": "image", ".mp3": "audio", ".ogg": "audio",
        ".wav": "audio", ".mp4": "video", ".pdf": "document",
    }
    environments = {
        str(item.get("environment")): item
        for item in manifest.get("environments", [])
        if isinstance(item, dict) and item.get("environment")
    }
    environment_reports: dict[str, dict[str, Any]] = {}
    for name, environment in environments.items():
        config_path = root / str(environment["config_path"])
        config = _load_yaml(config_path)
        paths = _layout_paths(config)
        file_inputs = sorted(
            {
                path
                for path in paths
                if _path_suffix(path) in NON_TEXT_SUFFIXES
            }
        )
        config_text = config_path.read_text(encoding="utf-8", errors="replace").lower()
        references = sorted(word for word in NON_TEXT_WORDS if word in config_text)
        internal_references = sorted(set(references) - {Path(path).stem.lower() for path in file_inputs})
        unsupported_inputs = [
            path for path in file_inputs
            if extension_modality.get(_path_suffix(path), "document") not in modalities
        ]
        unsupported = bool(unsupported_inputs)
        decision = (
            "unsupported_non_text_input_requires_provider_modality"
            if unsupported
            else "provider_modalities_compatible_no_input_conversion"
        )
        environment_reports[name] = {
            "environment": name,
            "config_path": str(config_path.relative_to(root)),
            "input_paths_inspected": paths,
            "non_text_input_paths": file_inputs,
            "unsupported_input_paths": unsupported_inputs,
            "non_text_references_in_generated_source": internal_references,
            "requires_non_text_input": bool(file_inputs),
            "provider": provider,
            "provider_input_modalities": sorted(modalities),
            "unsupported_for_provider": unsupported,
            "decision": decision,
            "notes": (
                f"{provider} declared modalities do not include one or more input file types; "
                "the case is retained in the inventory and marked unsupported."
                if unsupported
                else "No required input file type falls outside the provider's declared modalities."
            ),
        }
        if provider == "atria":
            environment_reports[name]["unsupported_for_atria_text_only"] = unsupported
    case_reports: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        if not isinstance(case, dict):
            continue
        environment = str(case.get("environment", ""))
        report = environment_reports.get(environment)
        if report is None:
            item = {
                "case_id": case.get("case_id"),
                "environment": environment,
                "requires_non_text_input": True,
                "unsupported_for_provider": True,
                "decision": "unsupported_environment_missing_from_inventory",
            }
        else:
            item = {
                "case_id": case.get("case_id"),
                "environment": environment,
                "requires_non_text_input": report["requires_non_text_input"],
                "unsupported_for_provider": report["unsupported_for_provider"],
                "decision": report["decision"],
            }
        if provider == "atria":
            item["unsupported_for_atria_text_only"] = item["unsupported_for_provider"]
        case_reports.append(item)
    unsupported_cases = [
        item["case_id"] for item in case_reports if item["unsupported_for_provider"]
    ]
    result = {
        "provider": provider,
        "model": model,
        "provider_input_modalities": sorted(modalities),
        "provider_input_modality": "text_only" if modalities == {"text"} else "declared_modalities",
        "selected_case_count": len(case_reports),
        "environments": list(environment_reports.values()),
        "cases": case_reports,
        "unsupported_case_ids": unsupported_cases,
        "all_selected_cases_provider_modality_compatible": not unsupported_cases,
        "conversion_performed": False,
        "omitted_case_ids": [],
    }
    # Keep the prior Atria report field for existing pilot tooling.
    if provider == "atria":
        result["all_selected_cases_text_only_compatible"] = not unsupported_cases
    return result
