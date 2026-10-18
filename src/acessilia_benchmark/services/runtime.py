"""Pinned evaluator checkout and Python runtime management."""

import json
import os
import shutil
import subprocess

from ..core.catalog import load_registry
from ..core.workspace import Workspace
from ..io import digest, read
from ..processes import git
from .render_tools import environment as render_environment

EVALUATION_PYTHON_VERSION = "3.11.17"


def evaluator(workspace: Workspace, dataset):
    spec = load_registry(workspace)[dataset]["evaluator"]
    repo = workspace.root / "vendor" / spec["directory"]
    if not (repo / ".git").exists() or git(repo, "rev-parse", "HEAD") != spec["commit"]:
        raise ValueError("Avaliador ausente ou revisão diferente; execute setup.")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"Avaliador com alterações locais: {repo}")
    return (repo, spec)


def uv_environment(workspace: Workspace):
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", str(workspace.root / "data/.cache/uv"))
    env.setdefault("UV_PYTHON_INSTALL_DIR", str(workspace.root / "data/.python"))
    return env


def setup(workspace: Workspace):
    if not shutil.which("uv"):
        raise ValueError("Instale uv: https://docs.astral.sh/uv/getting-started/installation/")
    for dataset, dataset_spec in load_registry(workspace).items():
        spec = dataset_spec["evaluator"]
        repo = workspace.root / "vendor" / spec["directory"]
        if not repo.exists():
            repo.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", spec["url"], str(repo)], check=True)
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError(f"Preserve/resolva as alterações locais antes de setup: {repo}")
        if git(repo, "rev-parse", "HEAD") != spec["commit"]:
            subprocess.run(["git", "-C", str(repo), "fetch", "origin", spec["commit"]], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "checkout", "--detach", spec["commit"]], check=True
            )
        evaluator(workspace, dataset)
    command = [
        "uv",
        "sync",
        "--project",
        str(workspace.root / "evaluation"),
        "--python",
        EVALUATION_PYTHON_VERSION,
    ]
    # Resolve once on a fresh checkout; preserve the local lock for subsequent runs.
    if (workspace.root / "evaluation/uv.lock").is_file():
        command.append("--frozen")
    subprocess.run(
        command,
        check=True,
        env=uv_environment(workspace),
    )
    print("Avaliadores e ambiente Python preparados com as versões fixadas.")


def runtime_versions(workspace: Workspace, profile, dataset=None, *, env=None):
    env = (
        env
        if env is not None
        else (render_environment(workspace) if profile == "full" else os.environ.copy())
    )
    versions = {
        "python": subprocess.check_output(
            [str(workspace.evaluation_python), "--version"], text=True, env=env
        ).strip()
    }
    versions["packages"] = json.loads(
        subprocess.check_output(
            [
                str(workspace.evaluation_python),
                "-c",
                "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))",
            ],
            text=True,
            env=env,
        )
    )
    if profile == "full":
        render_lock = workspace.root / "evaluation/render-tools.lock.json"
        versions["render_environment"] = {
            key: env.get(key, "")
            for key in ("TEXMFHOME", "TEXINPUTS", "FONTCONFIG_FILE", "CDM_CJK_FONT")
        }
        if render_lock.is_file():
            versions["render_tools_lock_sha256"] = digest(render_lock)
            versions["local_render_artifacts"] = {
                item["path"]: digest(workspace.root / "data/tools" / item["path"])
                for item in read(render_lock)["artifacts"]
                if (workspace.root / "data/tools" / item["path"]).is_file()
            }
        for command in (("pdflatex", "--version"), ("gs", "--version"), ("magick", "--version")):
            if not shutil.which(command[0], path=env.get("PATH", "")):
                raise ValueError(
                    f"CDM requer {command[0]}; consulte evaluation/README.md ou use basic."
                )
            versions[command[0]] = subprocess.check_output(
                command, text=True, env=env
            ).splitlines()[0]
        if (
            not shutil.which("kpsewhich", path=env.get("PATH", ""))
            or subprocess.run(["kpsewhich", "CJK.sty"], capture_output=True, env=env).returncode
        ):
            raise ValueError(
                "CDM requer recursos CJK do TeX Live; use basic ou prepare o runtime oficial."
            )
        if dataset == "drdocbench-dev":
            if not shutil.which("node", path=env.get("PATH", "")):
                raise ValueError(
                    "CDM do Dr.DocBench requer Node.js; use basic ou prepare o runtime oficial."
                )
            versions["node"] = subprocess.check_output(
                ["node", "--version"], text=True, env=env
            ).strip()
    return versions
