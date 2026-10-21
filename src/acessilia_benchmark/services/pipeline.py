"""One-command orchestration using the same sealed manual-run protocol."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..core.catalog import download, load_registry
from ..core.runs import prepare
from ..core.workspace import Workspace
from .doctor import resolve_python
from .evaluation import evaluate
from .inference import predict
from .render_tools import install as install_render_tools
from .runtime import runtime_versions, setup


def run_dataset(
    workspace: Workspace,
    dataset: str,
    repo: Path,
    *,
    name: str | None = None,
    python: Path | None = None,
    data_dir: Path | None = None,
    limit: int = 0,
    seed: int = 42,
    profile: str = "auto",
    timeout: float = 1800,
    evaluation_timeout: float = 1800,
    skip_setup: bool = False,
    offline: bool = False,
    window_size: int = 2,
) -> Path:
    if window_size not in (1, 2):
        raise ValueError("Janela deve ter uma ou duas páginas.")
    spec = load_registry(workspace)[dataset]
    if profile == "auto":
        profile = "full" if spec["evaluator"] else "runtime"
    if profile not in {"basic", "full", "runtime"}:
        raise ValueError("Perfil inválido.")
    if spec["evaluator"] is None and profile != "runtime":
        raise ValueError("Dataset sem referências; use --profile runtime ou auto.")
    if limit < 0 or timeout <= 0 or evaluation_timeout <= 0:
        raise ValueError("Limite deve ser >= 0 e timeouts devem ser positivos.")
    if offline and not skip_setup:
        raise ValueError("--offline requer --skip-setup e ambientes previamente preparados.")
    name = name or f"{dataset}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
    destination = workspace.run_dir(name)
    if destination.exists():
        raise ValueError("Rodada já existe; escolha outro nome para preservar os resultados.")
    repo = repo.expanduser().resolve()
    # Fail before downloads or environment setup when Core cannot execute.
    selected, _ = resolve_python(repo, python)
    data_dir = (data_dir or workspace.data).expanduser().resolve()
    manifest = data_dir / dataset / spec["revision"] / "download-manifest.json"
    if not manifest.is_file() and not offline:
        download(dataset, spec, data_dir)
    if not skip_setup:
        setup(workspace)
        if profile == "full":
            install_render_tools(workspace)
    if profile != "runtime":
        runtime_versions(workspace, profile, dataset)
    prepare(workspace, dataset, name, data_dir, limit, seed, window_size=window_size)
    predict(workspace, name, repo, selected, timeout)
    evaluate(workspace, name, profile, timeout=evaluation_timeout)
    report = destination / ("runtime-report" if profile == "runtime" else profile) / "report.md"
    print(f"Relatório → {report}", flush=True)
    return report
