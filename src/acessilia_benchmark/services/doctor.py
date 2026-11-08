"""Read-only checks of interpreters, evaluator checkouts and the Toolbox API."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..core.catalog import load_registry
from ..core.workspace import Workspace
from .runtime import evaluator
from .toolbox import check_toolbox, read_toolbox_settings

CORE_MODULES = ("agno", "fitz", "PIL", "fastapi", "docstruct", "acessilia_sdk")


def interpreter_info(python: Path, repo: Path) -> dict:
    program = """import importlib,importlib.util,json,sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + '/libs/docstruct/src', sys.argv[1] + '/libs/sdk/src']
names = ('agno', 'fitz', 'PIL', 'fastapi', 'docstruct', 'acessilia_sdk')
contracts = {}
for module, symbol in [('docstruct.export.markdown', 'document_to_markdown'),
                       ('scripts.bench.core', 'payload_to_canonical'),
                       ('backend.tools.toolbox_client', 'make_toolbox_client')]:
    try:
        contracts[module + ':' + symbol] = callable(getattr(importlib.import_module(module), symbol))
    except Exception:
        contracts[module + ':' + symbol] = False
try:
    import inspect
    from acessilia_sdk.toolbox.clients import ToolboxStructureClient
    contracts['ToolboxStructureClient.extract_structure:use_remote_cache'] = (
        'use_remote_cache' in inspect.signature(ToolboxStructureClient.extract_structure).parameters)
except Exception:
    contracts['ToolboxStructureClient.extract_structure:use_remote_cache'] = False
try:
    contracts['backend.config.settings:settings'] = hasattr(
        importlib.import_module('backend.config.settings'), 'settings')
except Exception:
    contracts['backend.config.settings:settings'] = False
print(json.dumps({'python': sys.version, 'prefix': sys.prefix, 'contracts': contracts,
                  'modules': {name: importlib.util.find_spec(name) is not None for name in names}}))
"""
    result = subprocess.run(
        [str(python), "-c", program, str(repo)],
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


def resolve_python(repo: Path, explicit: Path | None = None) -> tuple[Path, dict]:
    candidates = [explicit.expanduser().absolute()] if explicit else [repo / ".venv/bin/python"]
    if explicit is None and shutil.which("poetry"):
        result = subprocess.run(
            ["poetry", "-C", str(repo), "env", "info", "--executable"],
            text=True,
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            candidates.append(Path(result.stdout.strip()).absolute())
    errors = []
    for candidate in candidates:
        # Resolving this symlink would drop the virtual environment and its packages.
        try:
            info = interpreter_info(candidate, repo)
            missing = [name for name in CORE_MODULES if not info["modules"][name]]
            missing += [
                name for name, available in info.get("contracts", {}).items() if not available
            ]
            if not missing:
                return candidate, info
            errors.append(f"{candidate}: faltam {', '.join(missing)}")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"{candidate}: {type(error).__name__}")
    raise ValueError("Ambiente do Acessilia indisponível. Informe --python. " + "; ".join(errors))


def diagnose(
    workspace: Workspace, repo: Path | None, python: Path | None, toolbox_url: str | None
) -> dict:
    result = {
        "workspace": str(workspace.root),
        "evaluation_python": workspace.evaluation_python.is_file(),
        "datasets": {},
        "evaluators": {},
        "core": None,
        "toolbox": None,
    }
    for name, spec in load_registry(workspace).items():
        result["datasets"][name] = {
            "present": (
                workspace.data / name / spec["revision"] / "download-manifest.json"
            ).is_file(),
            "integrity": "checked by prepare, not by this presence probe",
        }
        if spec["evaluator"] is None:
            result["evaluators"][name] = {"ok": True, "required": False}
            continue
        try:
            _, locked = evaluator(workspace, name)
            result["evaluators"][name] = {"ok": True, "commit": locked["commit"]}
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            result["evaluators"][name] = {"ok": False, "error": str(error)}
    if repo is not None:
        try:
            resolved_repo = repo.expanduser().resolve()
            selected, info = resolve_python(resolved_repo, python)
            result["core"] = {"ok": True, "interpreter": str(selected), **info}
            config = read_toolbox_settings(selected, resolved_repo)
            endpoints = [toolbox_url] if toolbox_url else list(config.endpoints)
            providers = config.providers
            api_key = config.api_key
            pinned_providers = (
                tuple((provider, endpoints[0]) for provider, _ in config.pinned_providers)
                if toolbox_url
                else config.pinned_providers
            )
        except ValueError as error:
            result["core"] = {"ok": False, "error": str(error)}
            endpoints = [toolbox_url or os.environ.get("TOOLBOX_BASE_URL", "http://127.0.0.1:8002")]
            providers = ()
            api_key = ""
            pinned_providers = ()
    else:
        endpoints = [toolbox_url or os.environ.get("TOOLBOX_BASE_URL", "http://127.0.0.1:8002")]
        providers = ()
        api_key = ""
        pinned_providers = ()
    result["toolbox"] = check_toolbox(endpoints, providers, api_key, pinned_providers)
    result["ready_for_evaluation"] = result["evaluation_python"] and all(
        v["ok"] for v in result["evaluators"].values()
    )
    result["ready_for_inference"] = bool(
        result["core"] and result["core"]["ok"] and result["toolbox"]["ok"]
    )
    return result
