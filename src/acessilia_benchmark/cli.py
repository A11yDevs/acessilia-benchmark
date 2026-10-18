"""Command-line entrypoints for manual benchmark runs."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from .core.catalog import download, load_registry, verify
from .core.runs import import_predictions, prepare
from .core.workspace import Workspace
from .io import write
from .services.doctor import diagnose
from .services.evaluation import evaluate
from .services.inference import predict
from .services.render_tools import install as install_render_tools
from .services.runtime import setup
from .services.selfcheck import smoke


def main():
    workspace = Workspace.discover()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("setup")
    commands.add_parser("setup-render-tools", help="Instalar ferramentas locais de renderização.")
    for action in ("prepare", "smoke"):
        sub = commands.add_parser(action)
        sub.add_argument("dataset", choices=load_registry(workspace))
        sub.add_argument("--run", required=True)
        sub.add_argument("--data-dir", type=Path, default=workspace.root / "data")
        if action == "prepare":
            sub.add_argument(
                "--limit", type=int, default=10, help="Número de casos; 0 seleciona todos."
            )
            sub.add_argument("--seed", type=int, default=42)
    sub = commands.add_parser("predict")
    sub.add_argument("--run", required=True)
    sub.add_argument("--acessilia-repo", type=Path, required=True)
    sub.add_argument(
        "--python",
        type=Path,
        help="Interpretador do Acessilia; detecta .venv ou Poetry por padrão.",
    )
    sub.add_argument("--timeout", type=float, default=1800)
    sub = commands.add_parser("evaluate")
    sub.add_argument("--run", required=True)
    sub.add_argument("--profile", choices=["basic", "full"], default="basic")
    sub.add_argument("--timeout", type=float, default=1800)
    sub = commands.add_parser("doctor")
    sub.add_argument("--acessilia-repo", type=Path)
    sub.add_argument("--python", type=Path)
    sub.add_argument(
        "--toolbox-url", default=os.environ.get("TOOLBOX_BASE_URL", "http://127.0.0.1:8002")
    )
    sub.add_argument("--output", type=Path)
    sub = commands.add_parser("import-predictions")
    sub.add_argument("--run", required=True)
    sub.add_argument("--source", type=Path, required=True)
    sub.add_argument("--label", required=True)
    args = parser.parse_args()
    try:
        if args.action == "doctor":
            result = diagnose(workspace, args.acessilia_repo, args.python, args.toolbox_url)
            if args.output:
                write(args.output, result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not result["ready_for_evaluation"] or (
                args.acessilia_repo and not result["ready_for_inference"]
            ):
                parser.exit(1)
        elif args.action == "import-predictions":
            import_predictions(workspace, args.run, args.source, args.label)
        elif args.action == "setup-render-tools":
            install_render_tools(workspace)
        elif args.action == "setup":
            setup(workspace)
        elif args.action == "prepare":
            if args.limit < 0:
                raise ValueError("--limit deve ser >= 0.")
            prepare(
                workspace, args.dataset, args.run, args.data_dir.resolve(), args.limit, args.seed
            )
        elif args.action == "smoke":
            smoke(workspace, args.dataset, args.run, args.data_dir.resolve())
        elif args.action == "predict":
            if args.timeout <= 0:
                raise ValueError("--timeout deve ser positivo.")
            predict(workspace, args.run, args.acessilia_repo, args.python, args.timeout)
        elif args.action == "evaluate":
            evaluate(workspace, args.run, args.profile, timeout=args.timeout)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Erro: {error}\n")


def datasets_main():
    workspace = Workspace.discover()
    registry = load_registry(workspace)
    parser = argparse.ArgumentParser(description="Obter/verificar datasets com revisões fixadas.")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    for action in ("download", "verify"):
        sub = commands.add_parser(action)
        sub.add_argument("dataset", choices=registry)
        sub.add_argument("--data-dir", type=Path, default=workspace.data)
    args = parser.parse_args()
    try:
        if args.action == "list":
            for name, spec in registry.items():
                print(f"{name}: {spec['repo_id']} @ {spec['revision']} ({spec['split']})")
        else:
            action = download if args.action == "download" else verify
            action(args.dataset, registry[args.dataset], args.data_dir.expanduser().resolve())
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Erro: {error}\n")
