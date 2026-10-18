"""Read-only checks of interpreters, evaluator checkouts and the Toolbox API."""

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from ..core.catalog import load_registry
from ..core.workspace import Workspace
from .runtime import evaluator

CORE_MODULES = ("agno", "fitz", "PIL", "fastapi", "docstruct")


def interpreter_info(python: Path, repo: Path) -> dict:
    program = """import importlib.util,json,sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + '/libs/docstruct/src']
names = ('agno', 'fitz', 'PIL', 'fastapi', 'docstruct')
print(json.dumps({'python': sys.version, 'prefix': sys.prefix,
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
            if not missing:
                return candidate, info
            errors.append(f"{candidate}: faltam {', '.join(missing)}")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"{candidate}: {type(error).__name__}")
    raise ValueError("Ambiente do Acessilia indisponível. Informe --python. " + "; ".join(errors))


def check_toolbox(url: str) -> dict:
    health_url = url.rstrip("/") + "/v1/health"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            data = json.load(response)
        return {
            "ok": data.get("status") in {"healthy", "ok"},
            "health": data,
            "scope": "API health; provider execution is checked by inference",
        }
    except (OSError, ValueError, urllib.error.URLError) as error:
        return {"ok": False, "error": str(error)}


def diagnose(
    workspace: Workspace, repo: Path | None, python: Path | None, toolbox_url: str
) -> dict:
    result = {
        "workspace": str(workspace.root),
        "evaluation_python": workspace.evaluation_python.is_file(),
        "datasets": {},
        "evaluators": {},
        "core": None,
        "toolbox": check_toolbox(toolbox_url),
    }
    for name, spec in load_registry(workspace).items():
        result["datasets"][name] = {
            "present": (
                workspace.data / name / spec["revision"] / "download-manifest.json"
            ).is_file(),
            "integrity": "checked by prepare, not by this presence probe",
        }
        try:
            _, locked = evaluator(workspace, name)
            result["evaluators"][name] = {"ok": True, "commit": locked["commit"]}
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            result["evaluators"][name] = {"ok": False, "error": str(error)}
    if repo is not None:
        try:
            selected, info = resolve_python(repo.expanduser().resolve(), python)
            result["core"] = {"ok": True, "interpreter": str(selected), **info}
        except ValueError as error:
            result["core"] = {"ok": False, "error": str(error)}
    result["ready_for_evaluation"] = result["evaluation_python"] and all(
        v["ok"] for v in result["evaluators"].values()
    )
    result["ready_for_inference"] = bool(
        result["core"] and result["core"]["ok"] and result["toolbox"]["ok"]
    )
    return result
