#!/usr/bin/env python3
"""Ask whether a set of environments can run against one provider and model at all.

The question comes before any spending.  An account key exists
(``AGENTROUTER_API_KEY`` is among this repository's Actions secrets), a model is
wanted (anything whose id contains ``astra``), and six environments are wanted
(the three under ``envs/cat_theo/sheaf`` and the three under
``envs/recurrent_depth``).  Nothing in the repository could answer whether those
three facts meet, and the instrument that looks like it could answers wrongly::

    $ python tools/provider_preflight.py --provider agentrouter
    {"provider": "agentrouter", "status": "credential_error", "model_ids": [], ...}

``agentrouter`` is not a modelled provider: ``arena/secrets.py`` carries no entry
for it in ``PROVIDER_ENV`` or ``PROVIDER_DEFAULT_BASE``, so ``resolve_provider``
raises ``ValueError: unknown provider 'agentrouter'`` before any credential is
consulted and ``probe_provider`` flattens that into ``credential_error``.  A
present, working key and no key at all produce the same line, which is the one
answer that cannot be acted on.  Measured on this checkout; the modelled roster is
atria, cloudflare, custom, gemini, groq, huggingface, mercury, nvidia, openrouter.

So this tool separates the seven things that have to be true, in the order they
get expensive, and reports each with the evidence that decided it.

1. ``credential`` - is a key reachable from *here*, and under which provider name
   would the client send it?  Offline and free.  An Actions secret is not readable
   by any local process or API call (``GET /actions/secrets`` answers 403 to this
   credential), so from a workstation this stage says ``key_not_visible_here`` and
   names the workflow that has to run the remaining stages.
2. ``env_build`` - can each environment be generated, compiled, and can its
   deferred judge scripts be validated?  Offline and free.  This reuses
   ``suite_inventory``'s own per-case preflight rather than re-deriving it, so the
   inventory and this probe cannot drift apart.
3. ``judge_stack`` - do the judge and agent images pin what the judges import
   (``torch``), is that stack on this host, and does CI install it?  All six
   judges import torch, so a host without it can plan but cannot run an episode.
4. ``gate_status`` - would a score be an exact-instance gated verdict or a
   compile-only one?  ``instance_oracle_gate.REFERENCES`` decides.  Of the six,
   only ``rd_state_carry`` is in it, which bounds what a run can be used for
   before it is paid for: the other five can join a scoreboard, never a gate.
5. ``plan`` - how many cases do these environments make per matrix, and what does
   one rehearsal cost in API calls?
6. ``catalog`` - does ``GET /models`` answer with this key, and does the roster
   contain a model matching the filter?  Network, free, opt-in.
7. ``wire`` - does one real completion come back untruncated *and* parse as an
   action the episode loop accepts?  Network, one paid call, opt-in.  This is the
   stage that separates "the router serves the model" from "the model can drive an
   episode": ``arena/episode.py`` runs a text JSON action protocol, so a model
   that answers prose, or that a router truncates at ``max_tokens``, cannot run
   these environments however cheap it is.

Stages 6 and 7 need the key and are off unless ``--stage network``, ``--stage
wire`` or ``--stage all`` asks for them.  Nothing spends by default and the wire
stage is a single attempt with retries disabled.

Endpoints are never guessed.  Sending a bearer key to a host inferred from a
product name is how a credential leaks, so ``catalog`` and ``wire`` require
``--api-base``, ``providers.<name>.api_base`` in ``secret_key.json``, or
``AGENTROUTER_API_BASE`` in the environment, and refuse without one.  Output
follows ``provider_preflight``: no keys, no endpoints (host only), no raw bodies,
and every serialized string passes ``redact_text`` as a final defense.

Exit codes: 0 the answer is yes, gaps allowed; 1 something blocks or constrains
it; 2 this tool could not run.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.episode import SYSTEM_PROMPT, parse_action  # noqa: E402
from arena.providers import ProviderClient, ProviderError, open_no_redirect, require_https  # noqa: E402
from arena.secrets import (  # noqa: E402
    PROVIDER_DEFAULT_BASE,
    PROVIDER_ENV,
    load_secret_config,
    redact_text,
    resolve_provider,
)

# suite_inventory's per-case preflight is the repository's own definition of "this
# case can be generated and its judge is well formed".  Importing it - private name
# and all - is deliberate: a second implementation would be a second opinion, and
# the two would eventually disagree about what "buildable" means.
from tools.suite_inventory import _preflight_case, build_manifest  # noqa: E402
from tools.gate_context import verdict_relevant_files  # noqa: E402
from tools.instance_oracle_gate import REFERENCES  # noqa: E402

DEFAULT_PROVIDER = "agentrouter"
DEFAULT_KEY_ENVS: tuple[str, ...] = (
    "AGENTROUTER_API_KEY",
    "AGENT_ROUTER_API_KEY",
    "AGENTROUTER_API_TOKEN",
)
DEFAULT_BASE_ENVS: tuple[str, ...] = ("AGENTROUTER_API_BASE",)
DEFAULT_MODEL_FILTER = "astra"
DEFAULT_ENV_DIRS: tuple[str, ...] = ("envs/cat_theo/sheaf", "envs/recurrent_depth")
DEFAULT_MATRICES: tuple[str, ...] = ("representative", "pairwise")

# An unmodelled provider has to travel as ``custom``: that is the route this
# repository leaves open for a trial endpoint whose adapter has not been written
# yet.  Doing it silently is how an endpoint ends up sending fields the service
# never promised to honour, so the credential stage reports the substitution as a
# gap every single time it makes it.
FALLBACK_WIRE_PROVIDER = "custom"

OFFLINE_STAGES: tuple[str, ...] = ("credential", "env_build", "judge_stack", "gate_status", "plan")
NETWORK_STAGES: tuple[str, ...] = ("catalog",)
PAID_STAGES: tuple[str, ...] = ("wire",)

_JUDGE_DOCKERFILE = Path("shared/Dockerfile.judge")
_AGENT_DOCKERFILE = Path("shared/Dockerfile.agent")
_PIN_PATTERN = re.compile(r"\b(torch|torchvision)==([0-9][0-9a-zA-Z.+]*)")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _host_of(base: str | None) -> str | None:
    """Reduce an endpoint to its host: the base URL stays out of every artifact."""

    if not base:
        return None
    try:
        return urlsplit(base).hostname
    except ValueError:
        return None


def _sanitize(value: Any) -> Any:
    """Redact every serialized string, the way ``provider_preflight`` does."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {redact_text(str(key)): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [str(item["id"]) for item in data if isinstance(item, dict) and item.get("id") is not None]


def _request_id(headers: Mapping[str, Any] | None) -> str | None:
    for key, value in (headers or {}).items():
        if str(key).lower() in {"x-request-id", "request-id", "openrouter-request-id"}:
            return str(value)
    return None


def selected_environments(
    root: Path, *, env_dirs: Sequence[str] = DEFAULT_ENV_DIRS, explicit: Sequence[str] = ()
) -> dict[str, Any]:
    """Resolve the wanted environments from the registry, by directory or by name.

    Discovery is registry-first so the probe answers about the environments the
    suite would actually schedule.  A name that is not in the registry is reported
    rather than silently dropped: a typo in ``--env`` should not turn "can these six
    run?" into "can these five run?".
    """

    from tools.suite_inventory import _load_registry

    registry: dict[str, str] = dict(_load_registry(root))
    wanted_dirs = [str(item).rstrip("/") for item in env_dirs]
    discovered = {
        name: path
        for name, path in registry.items()
        if any(Path(path).as_posix().startswith(prefix + "/") for prefix in wanted_dirs)
    }
    named = {name: registry[name] for name in explicit if name in registry}
    missing = sorted(name for name in explicit if name not in registry)
    environments = dict(sorted({**discovered, **named}.items()))
    return {
        "environments": environments,
        "env_dirs": wanted_dirs,
        "requested_names": sorted(explicit),
        "names_not_in_registry": missing,
    }


# ---------------------------------------------------------------------------
# stage 1: credential
# ---------------------------------------------------------------------------


def stage_credential(
    provider: str,
    *,
    key_envs: Sequence[str],
    base_envs: Sequence[str],
    api_base: str | None,
    secret_path: Path | None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Establish what a request would be sent as, and whether a key is in reach."""

    env = dict(os.environ if environ is None else environ)
    modelled = provider in PROVIDER_ENV
    wire_provider = provider if modelled else FALLBACK_WIRE_PROVIDER
    key_env_tried = list(key_envs) if not modelled else list(PROVIDER_ENV[provider]) + list(key_envs)
    key_source = next((f"env:{name}" for name in dict.fromkeys(key_env_tried) if env.get(name)), None)

    base = api_base or next((env[name] for name in base_envs if env.get(name)), None)
    config, loaded_path = load_secret_config(secret_path)
    providers = config.get("providers")
    profiles: dict[str, Any] = providers if isinstance(providers, dict) else {}
    profile = profiles.get(provider) if isinstance(profiles.get(provider), dict) else {}
    profile_base = str(profile.get("api_base")) if profile.get("api_base") else None
    base = base or profile_base or (PROVIDER_DEFAULT_BASE.get(wire_provider) if modelled else None)
    if not base and wire_provider in profiles and isinstance(profiles[wire_provider], dict):
        fallback = profiles[wire_provider].get("api_base")
        base = str(fallback) if fallback else None
    if not base:
        base = str(profiles.get(wire_provider, {}).get("api_base") or "") or None

    notes: list[str] = []
    blockers: list[str] = []
    if not modelled:
        notes.append(
            f"{provider!r} is not a modelled provider (arena/secrets.py has no PROVIDER_ENV or "
            f"PROVIDER_DEFAULT_BASE entry), so a request would be sent as {wire_provider!r} with an "
            "explicit base and key-env; tools/provider_preflight.py cannot probe it at all and "
            "answers 'credential_error' whether or not a key exists"
        )
    resolve_error: str | None = None
    try:
        creds = resolve_provider(
            wire_provider,
            api_key=env.get(key_env_tried[0]) if key_source else None,
            api_key_env=key_env_tried[0] if key_env_tried else None,
            api_base=base,
            secret_path=secret_path,
            environ=env,
            require_key=False,
        )
        resolved_base: str | None = creds.api_base
        resolved_source = creds.source
    except (OSError, ValueError) as exc:
        creds = None
        resolved_base = base
        resolved_source = ""
        resolve_error = str(exc)

    if not key_source and not (creds is not None and creds.api_key):
        blockers.append(
            "no key is reachable from this process: an Actions secret is invisible here, so the "
            "catalog and wire stages have to run inside a workflow that maps it to an environment "
            "variable"
        )
        status = "key_not_visible_here"
    elif not resolved_base:
        blockers.append(
            "no endpoint is declared and none will be guessed: pass --api-base, set "
            + (base_envs[0] if base_envs else "the base environment variable")
            + ", or put providers."
            + wire_provider
            + ".api_base in secret_key.json"
        )
        status = "endpoint_not_declared"
    else:
        status = "ready"

    return {
        "stage": "credential",
        "status": status,
        "provider": provider,
        "modelled_provider": modelled,
        "wire_provider": wire_provider,
        "key_env_names_tried": list(dict.fromkeys(key_env_tried)),
        "key_source": key_source or (resolved_source if resolved_source.startswith("file") else None),
        "api_base_host": _host_of(resolved_base),
        "api_base_source": (
            "cli_or_env" if (api_base or any(env.get(name) for name in base_envs)) else
            ("profile" if profile_base else ("provider_default" if modelled else None))
        ),
        "secret_file": str(loaded_path) if loaded_path else None,
        "secret_file_provider_names": sorted(str(name) for name in profiles),
        "resolution_error": resolve_error,
        "blockers": blockers,
        "notes": notes,
        "hard_blocker": False,
    }


# ---------------------------------------------------------------------------
# stage 2: env_build
# ---------------------------------------------------------------------------


def stage_env_build(
    root: Path,
    environments: Mapping[str, str],
    cases_by_env: Mapping[str, list[dict[str, Any]]],
    *,
    cases_per_env: int,
) -> dict[str, Any]:
    """Generate, compile and judge-validate one case per environment, offline."""

    started = time.monotonic()
    per_env: dict[str, Any] = {}
    for name in sorted(environments):
        picked = list(cases_by_env.get(name, []))[: max(1, cases_per_env)]
        if not picked:
            per_env[name] = {"status": "not_in_manifest", "config_path": environments[name]}
            continue
        results = []
        for case in picked:
            outcome = dict(_preflight_case(case, root))
            outcome["case_id"] = str(case.get("case_id"))
            outcome["difficulty"] = str(case.get("difficulty"))
            results.append(outcome)
        statuses = {str(item["status"]) for item in results}
        per_env[name] = {
            "status": "ready" if statuses == {"ready"} else sorted(statuses)[0],
            "config_path": environments[name],
            "cases_checked": len(results),
            "cases": results,
        }
    not_ready = sorted(name for name, item in per_env.items() if item["status"] != "ready")
    return {
        "stage": "env_build",
        "status": "ready" if not not_ready else "build_failed",
        "environment_count": len(per_env),
        "environments": per_env,
        "not_ready": not_ready,
        "blockers": [
            f"{len(not_ready)} environment(s) cannot be built offline: " + ", ".join(not_ready)
        ] if not_ready else [],
        "notes": [],
        "hard_blocker": bool(not_ready),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# stage 3: judge_stack
# ---------------------------------------------------------------------------


def _image_pins(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        return {"present": False, "pins": {}, "floats": []}
    text = path.read_text(encoding="utf-8", errors="replace")
    pins = {name: version for name, version in _PIN_PATTERN.findall(text)}
    floats = sorted(
        {
            match
            for match in re.findall(r"\b(torch|torchvision)\b", text)
            if match not in pins
        }
    )
    return {"present": True, "pins": pins, "floats": floats}


def stage_judge_stack(
    root: Path,
    environments: Mapping[str, str],
    cases_by_env: Mapping[str, list[dict[str, Any]]],
    *,
    check_docker: bool,
    timeout: float,
) -> dict[str, Any]:
    """Compare what the judges import against what the images, this host and CI provide."""

    judges = _image_pins(root, _JUDGE_DOCKERFILE)
    agents = _image_pins(root, _AGENT_DOCKERFILE)
    wanted = sorted(judges["pins"]) or ["torch"]

    generated_dirs: dict[str, Path] = {}
    unchecked: list[str] = []
    for name in sorted(environments):
        cases = list(cases_by_env.get(name, []))
        generated = _generate_instance(root, cases[0]) if cases else None
        if generated is None:
            unchecked.append(name)
        else:
            generated_dirs[name] = generated
    try:
        imports = _judge_imports(root, generated_dirs)
    finally:
        for generated in generated_dirs.values():
            shutil.rmtree(generated, ignore_errors=True)
        for path in root.glob("provider-env-preflight-*"):
            shutil.rmtree(path, ignore_errors=True)

    host: dict[str, Any] = {}
    for module in wanted:
        if importlib.util.find_spec(module) is None:
            host[module] = {"present": False, "version": None}
            continue
        probe = subprocess.run(
            [sys.executable, "-c", f"import {module}; print(getattr({module}, '__version__', '?'))"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        host[module] = {
            "present": probe.returncode == 0,
            "version": probe.stdout.strip() or None,
        }

    docker_bin = shutil.which("docker")
    docker: dict[str, Any] = {"binary": bool(docker_bin)}
    if docker_bin and check_docker:
        try:
            info = subprocess.run(
                [docker_bin, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            docker["daemon"] = info.returncode == 0
            docker["server_version"] = info.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            docker["daemon"] = False
            docker["server_version"] = None
    elif docker_bin:
        docker["daemon"] = None

    ci_steps = _ci_judge_stack_steps(root)
    ci_pins: dict[str, str] = {}
    for entry in ci_steps:
        pins = entry.get("pins")
        if isinstance(pins, dict):
            ci_pins.update({str(key): str(value) for key, value in pins.items()})
    pin_drift = sorted(
        name for name, version in judges["pins"].items() if ci_pins.get(name) not in (None, version)
    )

    notes: list[str] = []
    blockers: list[str] = []
    missing_imports = {
        name: item["missing_imports"]
        for name, item in imports.items()
        if item.get("missing_imports")
    }
    if missing_imports:
        blockers.append(
            "a judge imports something the judge image does not install: "
            + "; ".join(
                f"{name} needs {', '.join(sorted(set(mods)))}"
                for name, mods in sorted(missing_imports.items())
            )
            + " - every episode would be paid for and then fail at grading"
        )
    broken_judges = sorted(
        name for name, item in imports.items() if item.get("status") == "judge_syntax_error"
    )
    if broken_judges:
        blockers.append(
            "a generated judge does not parse: " + ", ".join(broken_judges)
        )
    if unchecked:
        notes.append(
            "the judge imports of " + ", ".join(unchecked) + " were not read: no instance could be "
            "generated for them, which the env_build stage reports as its own blocker"
        )
    if pin_drift:
        blockers.append(
            "CI installs " + ", ".join(f"{name}=={ci_pins[name]}" for name in pin_drift)
            + " while shared/Dockerfile.judge pins "
            + ", ".join(f"{name}=={judges['pins'][name]}" for name in pin_drift)
        )

    missing_host = sorted(name for name, item in host.items() if not item["present"])
    host_can_run = bool(docker["binary"]) or not missing_host
    if missing_host:
        notes.append(
            "this host has no " + ", ".join(missing_host) + ", so --sandbox local cannot run an "
            "episode here; the pinned CPU judge stack is a container/CI property"
        )
    if not docker["binary"]:
        notes.append("no docker binary on this host, so --sandbox docker cannot run an episode here")
    if docker["binary"] and docker.get("daemon") is False:
        notes.append("a docker binary is present but the daemon did not answer")
    if agents["floats"]:
        notes.append(
            "shared/Dockerfile.agent installs " + ", ".join(agents["floats"]) + " unpinned while "
            "shared/Dockerfile.judge pins "
            + ", ".join(f"{key}=={value}" for key, value in sorted(judges["pins"].items()))
            + ", so the agent and the judge can disagree about the library that grades the work"
        )
    if ci_steps:
        notes.append(
            f"{len(ci_steps)} workflow(s) install the pinned CPU judge stack, so an episode can run "
            "in CI even where this host cannot"
        )

    if blockers:
        status = "blocked"
    elif (missing_host or not docker["binary"]) and ci_steps:
        status = "host_limited"
    elif missing_host or not docker["binary"]:
        status = "blocked"
        blockers.append(
            "no way to run the judges here or in CI: no host stack, no docker, and no workflow "
            "installs the pinned judge stack"
        )
    else:
        status = "ready"
    return {
        "stage": "judge_stack",
        "status": status,
        "judge_image": judges,
        "agent_image": agents,
        "judge_image_provides": sorted(_image_provides(root, _JUDGE_DOCKERFILE)),
        "judge_imports": imports,
        "judge_imports_unchecked": unchecked,
        "host_modules": host,
        "host_can_run_episodes": host_can_run,
        "docker": docker,
        "ci_installs_judge_stack": ci_steps,
        "ci_pins": dict(sorted(ci_pins.items())),
        "blockers": blockers,
        "notes": notes,
        "hard_blocker": bool(blockers),
    }


def _ci_judge_stack_steps(root: Path) -> list[dict[str, Any]]:
    """Find the workflows that install the judge stack: evidence CI can run episodes.

    Both shapes count, because the repository uses both: a step *named* for the
    stack, and a bare ``pip install`` of the same pins.  Only the pins are
    reported, so this stays a claim about the stack rather than about a workflow's
    internals.
    """

    found: list[dict[str, Any]] = []
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return found
    for path in sorted(workflow_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        names: list[str] = []
        pins: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip().removeprefix("- ").strip()
            if stripped.startswith("name:") and "judge stack" in stripped.lower():
                names.append(stripped.split(":", 1)[1].strip())
            if "pip install" in stripped or "torch==" in stripped:
                pins.update({name: version for name, version in _PIN_PATTERN.findall(stripped)})
        if names or pins:
            found.append({"workflow": path.name, "steps": names, "pins": dict(sorted(pins.items()))})
    return found


# pillow is the only judge-image install whose distribution name is not its import
# name; everything else the Dockerfile pip-installs imports as spelled.
_IMPORT_ALIASES: dict[str, str] = {"pillow": "PIL"}


def _pip_packages(text: str) -> set[str]:
    """Read package names out of a Dockerfile's pip installs, continuations included.

    The judge image's install is written across three physical lines -
    ``RUN pip install --no-cache-dir \\`` then the pinned packages, then a second
    ``pip install`` for the unpinned ones - so a line-by-line read that looks for
    ``pip install`` finds the flags and misses every package that matters.  Logical
    lines are joined first, then the index URLs and flags are dropped: what is left
    is the set of import names the image actually provides.
    """

    logical = re.sub(r"\\\s*\n", " ", text)
    provides: set[str] = set()
    for line in logical.splitlines():
        if "pip install" not in line:
            continue
        for command in re.split(r"&&|\|\|", line):
            if "pip install" not in command:
                continue
            # Drop the Dockerfile instruction word, then everything after an index
            # flag: neither `RUN` nor a wheel URL is a package.
            command = command[command.index("pip install") :]
            command = re.split(r"--index-url|--extra-index-url|\s-i\s", command, maxsplit=1)[0]
            for token in command.split():
                if token.startswith("-") or "://" in token or "/" in token:
                    continue
                name = re.split(r"[=<>!~\[;@]", token, maxsplit=1)[0].strip().lower()
                if name in {"pip", "install", "python", "m"} or not name:
                    continue
                provides.add(_IMPORT_ALIASES.get(name, name))
    return provides


def _image_provides(root: Path, dockerfile: Path) -> set[str]:
    """Read the import names a judge image installs, from its own Dockerfile."""

    path = root / dockerfile
    if not path.is_file():
        return set()
    provides = _pip_packages(path.read_text(encoding="utf-8", errors="replace"))
    # The layout copies shared/*.py into the image next to the judge, so those
    # modules are importable there without being installed by pip.
    return provides | {item.stem for item in (root / "shared").glob("*.py")}


def _generate_instance(root: Path, case: Mapping[str, Any]) -> Path | None:
    """Generate one instance and leave it on disk, so its real files can be read.

    The command mirrors ``suite_inventory._preflight_case``'s exactly; the only
    difference is that this one does not delete the tree afterwards, because the
    point is to look at what generation actually produced.
    """

    temp_dir = Path(tempfile.mkdtemp(prefix="provider-env-preflight-", dir=root))
    output_name = temp_dir.name + "-generated"
    output_dir = root / output_name
    command = [
        sys.executable,
        "generate_env.py",
        "--env",
        str(case.get("environment")),
        "--name",
        output_name,
        "--difficulty",
        ",".join(str(value) for value in (case.get("difficulty_levels") or {}).values()),
        "--seed",
        str(case.get("seed", 0)),
    ]
    interventions = case.get("interventions")
    if interventions:
        command += ["--interventions", str(interventions)]
    try:
        generated = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        return None
    if generated.returncode != 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        return None
    return output_dir


def _judge_imports(root: Path, generated_dirs: Mapping[str, Path]) -> dict[str, Any]:
    """Collect what the *generated* judges import and whether the judge image has it.

    A judge that imports something the image does not install fails at grading
    time, after the rollout has already been paid for, so this is worth knowing
    before the wire stage rather than after an episode.  It reads generated
    instances rather than the templates in ``envs/``: those carry ``%%PLACEHOLDER%%``
    tokens and are not Python until generation substitutes them, so parsing a
    template reports a syntax error for every environment in the repository.
    Deferred scripts embedded in a judge stay ``suite_inventory``'s
    ``validate_generated_judge`` problem and are covered by ``env_build``.
    """

    image_provides = _image_provides(root, _JUDGE_DOCKERFILE)
    stdlib = set(sys.stdlib_module_names)
    per_env: dict[str, Any] = {}
    for name, generated in sorted(generated_dirs.items()):
        judge_files = sorted((generated / "judge").glob("*.py"))
        if not judge_files:
            per_env[name] = {"status": "judge_missing", "imports": [], "missing_imports": []}
            continue
        local = {path.stem for path in judge_files}
        local |= {path.stem for path in (generated / "agent" / "workspace").glob("*.py")}
        local |= {path.stem for path in (generated / "agent" / "tools").glob("*.py")}
        imported: set[str] = set()
        syntax_error: str | None = None
        for judge in judge_files:
            try:
                tree = ast.parse(judge.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:
                syntax_error = f"{judge.name}: {exc}"
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
        missing = sorted(
            item
            for item in imported
            if item not in stdlib and item not in image_provides and item not in local
        )
        entry: dict[str, Any] = {
            "status": "imports_satisfied" if not missing and not syntax_error else "imports_missing",
            "imports": sorted(imported),
            "missing_imports": missing,
            "judge_files": [path.name for path in judge_files],
        }
        if syntax_error:
            entry["status"] = "judge_syntax_error"
            entry["error"] = syntax_error
        per_env[name] = entry
    return per_env


# ---------------------------------------------------------------------------
# stage 4: gate_status
# ---------------------------------------------------------------------------


def stage_gate_status(root: Path, environments: Mapping[str, str]) -> dict[str, Any]:
    """Say what kind of verdict each environment can produce, before it is paid for."""

    closure = {path.relative_to(root).as_posix() for path in verdict_relevant_files()}
    per_env: dict[str, Any] = {}
    for name, config_path in sorted(environments.items()):
        prefix = str(Path(config_path).parent).replace("\\", "/")
        reference = REFERENCES.get(name)
        per_env[name] = {
            "exact_instance_reference": (reference[1] if reference else None),
            "graded_by": "exact_instance_gate" if reference else "compile_only",
            "verdict_relevant_files": sorted(item for item in closure if item.startswith(prefix + "/")),
        }
    compile_only = sorted(name for name, item in per_env.items() if item["graded_by"] == "compile_only")
    notes = [
        f"{len(compile_only)} of {len(per_env)} environments are absent from "
        "instance_oracle_gate.REFERENCES (" + ", ".join(compile_only) + "), so they are generated and "
        "compiled but never gated: a score from them is a scoreboard row, not an exact-instance verdict"
        if compile_only else ""
    ]
    notes.append(
        "every one of these environments is inside the gate closure (tools/gate_context.py), so "
        "editing one re-grades a running campaign's exact-instance gate rows"
    )
    return {
        "stage": "gate_status",
        "status": "ready",
        "environments": per_env,
        "compile_only": compile_only,
        "blockers": [],
        "notes": [note for note in notes if note],
        "hard_blocker": False,
    }


# ---------------------------------------------------------------------------
# stage 5: plan
# ---------------------------------------------------------------------------


def stage_plan(
    root: Path,
    environments: Mapping[str, str],
    *,
    matrices: Sequence[str],
    max_steps: int,
    max_tokens: int,
    api_base_token: str,
    key_env: str | None,
    wire_provider: str,
    model: str | None,
) -> dict[str, Any]:
    """Count the cases each matrix would schedule and price one rehearsal."""

    per_matrix: dict[str, Any] = {}
    for matrix in matrices:
        manifest = build_manifest(root=root, matrix=matrix, seeds=[0], dry_run=True)
        cases = [case for case in manifest.get("cases", []) if case.get("environment") in environments]
        by_env: dict[str, int] = {}
        for case in cases:
            name = str(case.get("environment"))
            by_env[name] = by_env.get(name, 0) + 1
        per_matrix[matrix] = {
            "case_count": len(cases),
            "by_environment": dict(sorted(by_env.items())),
            "estimated_api_calls_at_max_steps": len(cases) * max(1, max_steps),
        }
    manifest_path = Path("runs/provider_env_preflight_manifest.json")
    model_token = model or "<model-id-from-catalog>"
    # The endpoint stays out of the report the same way the key does: a command
    # that names the environment variable holding it is copy-pasteable and leaks
    # nothing, and provider_preflight's output contract already forbids endpoints.
    base_token = api_base_token or "<api-base>"
    common = [
        "--manifest",
        str(manifest_path),
        "--provider",
        wire_provider,
        "--model",
        model_token,
        "--api-base",
        base_token,
        "--api-key-env",
        key_env or (DEFAULT_KEY_ENVS[0] if DEFAULT_KEY_ENVS else "API_KEY"),
    ]
    commands = {
        "emit_manifest": (
            f"python tools/provider_env_preflight.py --stage offline --matrix {matrices[-1]} "
            f"--emit-manifest {manifest_path}"
        ),
        "dry_run": "python tools/run_suite.py " + " ".join(common) + " --dry-run --max-cases 1",
        "one_case_rehearsal": (
            "python tools/run_suite.py " + " ".join(common)
            + f" --sandbox docker --max-cases 1 --max-steps {max_steps} --max-tokens {max_tokens} "
            f"--max-api-calls {max_steps} --max-wall-seconds 900"
        ),
    }
    return {
        "stage": "plan",
        "status": "ready",
        "matrices": per_matrix,
        "manifest_path": str(manifest_path),
        "commands": commands,
        "blockers": [],
        "notes": [
            "the counts are cases, not spend: one case is at most --max-steps completions, and the "
            "rehearsal command above bounds calls, tokens and wall time so a first run cannot run away"
        ],
        "hard_blocker": False,
    }


def emit_manifest(
    root: Path, environments: Mapping[str, str], matrix: str, out_path: Path
) -> dict[str, Any]:
    """Write a manifest restricted to the selected environments, for ``run_suite.py``."""

    manifest = dict(build_manifest(root=root, matrix=matrix, seeds=[0], dry_run=True))
    manifest["environments"] = [
        item for item in manifest.get("environments", []) if item.get("environment") in environments
    ]
    manifest["cases"] = [case for case in manifest.get("cases", []) if case.get("environment") in environments]
    manifest["selection"] = {
        "selected_environments": sorted(environments),
        "matrix": matrix,
        "selected_by": "tools/provider_env_preflight.py",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"case_count": len(manifest["cases"]), "path": str(out_path), "matrix": matrix}


# ---------------------------------------------------------------------------
# stage 6: catalog
# ---------------------------------------------------------------------------


def stage_catalog(
    *,
    wire_provider: str,
    api_base: str,
    api_key: str,
    model_filter: str,
    timeout: float,
) -> dict[str, Any]:
    """List the roster with the account's own key and look for the wanted model."""

    started = time.monotonic()
    needle = model_filter.strip().lower()
    try:
        require_https(api_base)
        url = api_base.rstrip("/") + "/models"
        req = request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="GET",
        )
        with open_no_redirect(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
            request_id = _request_id(getattr(response, "headers", None))
        ids = _model_ids(json.loads(body))
    except error.HTTPError as exc:
        return {
            "stage": "catalog",
            "status": "http_error",
            "status_code": int(exc.code),
            "request_id": _request_id(exc.headers),
            "model_count": 0,
            "matched_models": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
            "blockers": [f"GET /models answered HTTP {exc.code}: the key or the endpoint is wrong"],
            "notes": [],
            "hard_blocker": True,
        }
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "stage": "catalog",
            "status": "request_error",
            "error_type": type(exc).__name__,
            "model_count": 0,
            "matched_models": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
            "blockers": [f"GET /models did not complete ({type(exc).__name__})"],
            "notes": [],
            "hard_blocker": True,
        }
    matched = sorted(item for item in ids if needle in item.lower())
    result: dict[str, Any] = {
        "stage": "catalog",
        "status": "reachable",
        "status_code": status_code,
        "model_count": len(ids),
        "matched_models": matched[:50],
        "matched_count": len(matched),
        "model_filter": model_filter,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "blockers": [],
        "notes": [],
        "hard_blocker": False,
    }
    if request_id is not None:
        result["request_id"] = request_id
    if not ids:
        result["status"] = "empty_roster"
        result["blockers"] = [
            "GET /models answered 200 with no model ids, so this endpoint is not an "
            "OpenAI-compatible catalog and needs its own adapter rather than 'custom'"
        ]
        result["hard_blocker"] = True
    elif not matched:
        result["status"] = "model_not_in_catalog"
        result["blockers"] = [
            f"no model id contains {model_filter!r} among {len(ids)} listed; the roster sample is in "
            "model_ids_sample"
        ]
        result["hard_blocker"] = True
        result["model_ids_sample"] = sorted(ids)[:50]
    return result


# ---------------------------------------------------------------------------
# stage 7: wire
# ---------------------------------------------------------------------------


def stage_wire(
    *,
    wire_provider: str,
    api_base: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: float,
    client_factory: Any = None,
) -> dict[str, Any]:
    """One real completion, judged by whether the episode loop could use it.

    The prompt is ``arena.episode.SYSTEM_PROMPT`` and the observation is shaped like
    ``format_messages``' user turn, so the probe asks for the thing an episode
    actually asks for.  A 200 with prose in it is a failure here and a success
    everywhere else, which is the point.
    """

    factory = client_factory or (
        lambda: ProviderClient(
            wire_provider,
            api_key,
            api_base=api_base,
            timeout=timeout,
            max_retries=0,
            max_http_attempts=1,
        )
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Current observation:\nWorkspace files: prompt.md, visible_tests.py\n"
                "No command has been run yet. Return exactly one JSON action."
            ),
        },
    ]
    started = time.monotonic()
    try:
        completion = factory().complete(
            model=model, messages=messages, max_tokens=max_tokens, temperature=0.0
        )
    except ProviderError as exc:
        return {
            "stage": "wire",
            "status": "provider_error",
            "error_type": getattr(exc, "error_type", type(exc).__name__),
            "status_code": getattr(exc, "status_code", None),
            "request_id": getattr(exc, "request_id", None),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "blockers": [
                f"the endpoint refused one completion ({getattr(exc, 'error_type', 'provider_error')})"
            ],
            "notes": [str(getattr(exc, "body", ""))[:400]],
            "hard_blocker": True,
        }
    except (OSError, ValueError, TimeoutError) as exc:
        return {
            "stage": "wire",
            "status": "request_error",
            "error_type": type(exc).__name__,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "blockers": [f"one completion did not complete ({type(exc).__name__})"],
            "notes": [],
            "hard_blocker": True,
        }

    content = str(completion.content or "")
    action, invalid_note = parse_action(content)
    finish_reason = completion.finish_reason
    blockers: list[str] = []
    notes: list[str] = []
    if finish_reason == "length":
        blockers.append(
            f"the completion was cut off at max_tokens={max_tokens}; an episode needs a whole action "
            "per step, so raise --max-tokens or the router is clamping it"
        )
    if action is None:
        blockers.append(
            "the answer did not parse as an action the episode loop accepts"
            + (f" ({invalid_note})" if invalid_note else "")
        )
    if not content.strip():
        blockers.append("the completion carried no content")
    if completion.reasoning_content_length:
        notes.append(
            f"the response carries a separate reasoning channel ({completion.reasoning_content_length} "
            "chars); arena/episode.py only reads controlled reasoning for mercury and atria, so it "
            "would be billed and ignored"
        )
    usage = completion.usage if isinstance(completion.usage, dict) else {}
    return {
        "stage": "wire",
        "status": "ok" if not blockers else "unusable",
        "model_requested": completion.requested_model,
        "model_resolved": completion.resolved_model,
        "status_code": completion.status_code,
        "finish_reason": finish_reason,
        "content_chars": len(content),
        "content_prefix": content[:200],
        "action_parsed": bool(action),
        "action_type": str(action.get("type") or action.get("cmd") or "")[:40] if action else None,
        "reasoning_content_length": completion.reasoning_content_length,
        "latency_ms": completion.latency_ms,
        "request_id": completion.request_id,
        "usage": {str(key): usage[key] for key in sorted(usage)},
        "blockers": blockers,
        "notes": notes,
        "hard_blocker": bool(blockers),
    }


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


def verdict_for(stages: list[dict[str, Any]], *, asked_for_network: bool) -> dict[str, Any]:
    """Collapse the stage evidence into one answer and the shortest route forward."""

    by_name = {str(stage["stage"]): stage for stage in stages}
    blockers: list[str] = []
    gaps: list[str] = []
    for stage in stages:
        for blocker in stage.get("blockers", []):
            blockers.append(f"{stage['stage']}: {blocker}")
        for note in stage.get("notes", []):
            gaps.append(f"{stage['stage']}: {note}")
    hard = [stage["stage"] for stage in stages if stage.get("hard_blocker")]
    credential = by_name.get("credential", {})
    catalog = by_name.get("catalog")
    wire = by_name.get("wire")

    if hard and not (credential.get("status") == "key_not_visible_here" and not asked_for_network):
        status = "blocked"
    elif credential.get("status") == "key_not_visible_here" and catalog is None:
        status = "unknown_needs_ci"
    elif wire is not None and wire.get("status") == "ok" and not hard:
        status = "possible_with_gaps" if gaps else "possible"
    elif catalog is not None and catalog.get("status") == "reachable" and not hard:
        status = "possible_with_gaps"
    elif hard:
        status = "blocked"
    else:
        status = "possible_with_gaps"

    next_step = "run the offline stages in CI, where the secret exists"
    if status == "blocked":
        next_step = "fix the first blocker; the stages are ordered cheapest first"
    elif catalog is None and credential.get("status") == "ready":
        next_step = "re-run with --stage network to list the roster and find the model id"
    elif wire is None and catalog is not None:
        next_step = "re-run with --stage wire to spend one completion on the protocol question"
    elif status in {"possible", "possible_with_gaps"}:
        next_step = "emit the manifest and run the bounded rehearsal in the plan stage's commands"
    return {
        "verdict": status,
        "hard_blockers": hard,
        "blockers": blockers,
        "gaps": gaps,
        "next_step": next_step,
    }


def run_preflight(
    *,
    root: Path = ROOT,
    provider: str = DEFAULT_PROVIDER,
    key_envs: Sequence[str] = DEFAULT_KEY_ENVS,
    base_envs: Sequence[str] = DEFAULT_BASE_ENVS,
    api_base: str | None = None,
    secret_path: Path | None = None,
    model: str | None = None,
    model_filter: str = DEFAULT_MODEL_FILTER,
    env_dirs: Sequence[str] = DEFAULT_ENV_DIRS,
    env_names: Sequence[str] = (),
    stage: str = "offline",
    matrices: Sequence[str] = DEFAULT_MATRICES,
    cases_per_env: int = 1,
    max_steps: int = 30,
    max_tokens: int = 1024,
    wire_max_tokens: int = 96,
    timeout: float = 30.0,
    check_docker: bool = False,
    environ: Mapping[str, str] | None = None,
    client_factory: Any = None,
) -> dict[str, Any]:
    """Run the selected stages and return one redacted report."""

    wanted = selected_environments(root, env_dirs=env_dirs, explicit=env_names)
    environments: dict[str, str] = dict(wanted["environments"])
    asked_for_network = stage in {"network", "wire", "all"}
    asked_for_wire = stage in {"wire", "all"}

    # One manifest, shared by the stages that need cases.  Building it is the
    # expensive part of the offline half, and two builds could disagree with each
    # other about what exists if the registry changed underneath them mid-run.
    representative = build_manifest(root=root, matrix="representative", seeds=[0], dry_run=True)
    cases_by_env: dict[str, list[dict[str, Any]]] = {name: [] for name in environments}
    for case in representative.get("cases", []):
        name = str(case.get("environment"))
        if name in cases_by_env:
            cases_by_env[name].append(case)

    credential = stage_credential(
        provider,
        key_envs=key_envs,
        base_envs=base_envs,
        api_base=api_base,
        secret_path=secret_path,
        environ=environ,
    )
    stages: list[dict[str, Any]] = [
        credential,
        {"stage": "selection", "status": "ready", **wanted, "blockers": [], "notes": []},
    ]
    if wanted["names_not_in_registry"]:
        stages[1]["blockers"] = [
            "requested environment names missing from envs/registry.yaml: "
            + ", ".join(wanted["names_not_in_registry"])
        ]
        stages[1]["status"] = "names_missing"
        stages[1]["hard_blocker"] = True

    stages.append(stage_env_build(root, environments, cases_by_env, cases_per_env=cases_per_env))
    stages.append(
        stage_judge_stack(
            root, environments, cases_by_env, check_docker=check_docker, timeout=timeout
        )
    )
    stages.append(stage_gate_status(root, environments))
    env = dict(os.environ if environ is None else environ)
    base_env_set = next((name for name in base_envs if env.get(name)), None)
    # The endpoint stays out of every artifact, so the rehearsal command names the
    # variable that holds it instead of the URL: copy-pasteable, and leak-free.
    api_base_token = f"${base_env_set}" if base_env_set else "<api-base>"
    stages.append(
        stage_plan(
            root,
            environments,
            matrices=matrices,
            max_steps=max_steps,
            max_tokens=max_tokens,
            api_base_token=api_base_token,
            key_env=(credential.get("key_env_names_tried") or [None])[0],
            wire_provider=str(credential.get("wire_provider") or FALLBACK_WIRE_PROVIDER),
            model=model,
        )
    )

    key = ""
    if credential.get("key_source"):
        source = str(credential["key_source"])
        if source.startswith("env:"):
            key = str(env.get(source.split(":", 1)[1], ""))
    base = api_base or next((env[name] for name in base_envs if env.get(name)), None)
    if asked_for_network and key and base:
        catalog = stage_catalog(
            wire_provider=str(credential["wire_provider"]),
            api_base=base,
            api_key=key,
            model_filter=model_filter,
            timeout=timeout,
        )
        stages.append(catalog)
        matched = list(catalog.get("matched_models") or [])
        wire_model = model or (matched[0] if matched else None)
        if asked_for_wire and wire_model:
            stages.append(
                stage_wire(
                    wire_provider=str(credential["wire_provider"]),
                    api_base=base,
                    api_key=key,
                    model=wire_model,
                    max_tokens=wire_max_tokens,
                    timeout=timeout,
                    client_factory=client_factory,
                )
            )
        elif asked_for_wire:
            stages.append(
                {
                    "stage": "wire",
                    "status": "skipped",
                    "blockers": ["no model to probe: the catalog stage did not match one"],
                    "notes": [],
                    "hard_blocker": True,
                }
            )
    elif asked_for_network:
        stages.append(
            {
                "stage": "catalog",
                "status": "skipped",
                "blockers": [str(item) for item in credential.get("blockers", [])]
                or ["no key and endpoint pair is available to this process"],
                "notes": [],
                "hard_blocker": False,
            }
        )

    report = {
        "schema_version": 1,
        "event": "provider_env_preflight",
        "checked_at": _utc_now(),
        "question": {
            "provider": provider,
            "model_filter": model_filter,
            "model": model,
            "environments": sorted(environments),
            "stage": stage,
            "paid_stage_requested": asked_for_wire,
        },
        "stages": stages,
    }
    report["verdict"] = verdict_for(stages, asked_for_network=asked_for_network)
    return _sanitize(report)


def summarize(report: Mapping[str, Any]) -> str:
    """The human answer: one line per stage, then the verdict and the next step."""

    lines: list[str] = []
    question = report.get("question", {})
    lines.append(
        f"Can {len(question.get('environments', []))} environment(s) run on "
        f"{question.get('provider')} / {question.get('model_filter') or question.get('model')}?"
    )
    for stage in report.get("stages", []):
        name = str(stage.get("stage"))
        status = str(stage.get("status"))
        detail = ""
        if name == "env_build":
            detail = f" ({stage.get('environment_count')} generated, compiled, judge-validated)"
        elif name == "plan":
            matrices = stage.get("matrices", {})
            detail = " (" + ", ".join(
                f"{key}: {item.get('case_count')} cases" for key, item in sorted(matrices.items())
            ) + ")"
        elif name == "catalog":
            detail = f" ({stage.get('model_count')} models, {stage.get('matched_count')} matched)"
        elif name == "gate_status":
            detail = f" ({len(stage.get('compile_only', []))} compile-only)"
        elif name == "selection":
            detail = " (" + ", ".join(sorted(stage.get("environments", {}))) + ")"
        lines.append(f"- {name}: {status}{detail}")
        for blocker in stage.get("blockers", []):
            lines.append(f"    blocker: {blocker}")
        for note in stage.get("notes", []):
            lines.append(f"    note: {note}")
    verdict = report.get("verdict", {})
    lines.append("")
    lines.append(f"VERDICT: {verdict.get('verdict')}")
    lines.append(f"NEXT: {verdict.get('next_step')}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument(
        "--api-key-env",
        action="append",
        dest="key_envs",
        default=None,
        help="environment variable that holds the key; repeatable, tried in order",
    )
    parser.add_argument("--api-base-env", action="append", dest="base_envs", default=None)
    parser.add_argument("--api-base", default=None, help="endpoint; never guessed, required for network stages")
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--model", default=None, help="exact model id for the wire stage")
    parser.add_argument("--model-contains", default=DEFAULT_MODEL_FILTER, dest="model_filter")
    parser.add_argument("--env", action="append", dest="env_names", default=[])
    parser.add_argument("--env-dir", action="append", dest="env_dirs", default=None)
    parser.add_argument(
        "--stage",
        choices=("offline", "network", "wire", "all"),
        default="offline",
        help="offline is free; network lists the roster; wire spends one completion",
    )
    parser.add_argument("--matrix", action="append", dest="matrices", default=None)
    parser.add_argument("--cases-per-env", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--wire-max-tokens", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--check-docker", action="store_true", help="ask the docker daemon, not just PATH")
    parser.add_argument("--emit-manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("runs/provider_env_preflight.json"))
    parser.add_argument("--json-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_preflight(
            root=args.root,
            provider=args.provider,
            key_envs=tuple(args.key_envs or DEFAULT_KEY_ENVS),
            base_envs=tuple(args.base_envs or DEFAULT_BASE_ENVS),
            api_base=args.api_base,
            secret_path=args.secrets,
            model=args.model,
            model_filter=args.model_filter,
            env_dirs=tuple(args.env_dirs or DEFAULT_ENV_DIRS),
            env_names=tuple(args.env_names or ()),
            stage=args.stage,
            matrices=tuple(args.matrices or DEFAULT_MATRICES),
            cases_per_env=args.cases_per_env,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            wire_max_tokens=args.wire_max_tokens,
            timeout=args.timeout,
            check_docker=args.check_docker,
        )
        if args.emit_manifest:
            wanted = selected_environments(
                args.root, env_dirs=tuple(args.env_dirs or DEFAULT_ENV_DIRS), explicit=tuple(args.env_names or ())
            )
            matrix = (args.matrices or DEFAULT_MATRICES)[-1]
            report["emitted_manifest"] = emit_manifest(
                args.root, wanted["environments"], matrix, args.emit_manifest
            )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "event": "provider_env_preflight",
                    "status": "preflight_error",
                    "error_type": type(exc).__name__,
                    "error": redact_text(str(exc))[:2000],
                }
            ),
            file=sys.stderr,
        )
        return 2

    if args.json_only:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(summarize(report))
    verdict = str(report["verdict"]["verdict"])
    if os.environ.get("GITHUB_RUN_ID"):
        # ::notice:: and ::warning:: because the Actions log endpoints are closed to
        # the credential that can read everything else about a run: an annotation is
        # the only output of a job that survives it.
        level = "notice" if verdict in {"possible", "possible_with_gaps"} else "warning"
        print(f"::{level}::provider env preflight: {verdict} ({args.provider})")
        for blocker in report["verdict"]["blockers"][:8]:
            print(f"::warning::{blocker}")
    return 0 if verdict in {"possible", "possible_with_gaps"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
