"""Execute pinned official evaluators against complete predictions."""

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ..core.runs import load_plan, validate_predictions
from ..core.workspace import Workspace
from ..io import digest, read, seal, write
from ..processes import run_logged
from ..reporting import summarize
from .render_tools import environment as render_environment
from .runtime import evaluator, runtime_versions, uv_environment


def config_for(destination, plan, profile):
    metrics = {
        "text_block": {"metric": ["Edit_dist"]},
        "display_formula": {
            "metric": ["Edit_dist"] + (["CDM"] if profile == "full" else []),
            "cdm_workers": 1,
        },
        "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": 1},
        "reading_order": {"metric": ["Edit_dist"]},
    }
    dr = plan["dataset"] == "drdocbench-dev"
    ground_truth = (
        str(Path(plan["snapshot"]) / "dev") if dr else str(destination / "ground-truth.json")
    )
    return {
        "end2end_eval": {
            "metrics": metrics,
            "dataset": {
                "dataset_name": "multipage_end2end_dataset" if dr else "end2end_dataset",
                "ground_truth": {"data_path": ground_truth},
                "prediction": {"data_path": str(destination / "predictions")},
                "match_method": "quick_match",
                "match_workers": 1,
                "quick_match_truncated_timeout_sec": 300,
                "match_timeout_sec": 420,
                "timeout_fallback_max_chunk_span": 10,
                "timeout_fallback_order_penalty": 0.1,
            },
        }
    }


def evaluate(workspace: Workspace, name, profile, timeout: float = 1800):
    if profile not in {"basic", "full"}:
        raise ValueError("Perfil inválido; use basic ou full.")
    if timeout <= 0:
        raise ValueError("Timeout deve ser positivo.")
    destination, plan = load_plan(workspace, name)
    hashes = validate_predictions(destination, plan)
    repo, spec = evaluator(workspace, plan["dataset"])
    if not workspace.evaluation_python.is_file():
        raise ValueError("Ambiente do avaliador ausente; execute setup.")
    subprocess.run(
        [
            "uv",
            "sync",
            "--project",
            str(workspace.root / "evaluation"),
            "--frozen",
            "--offline",
            "--quiet",
        ],
        check=True,
        env=uv_environment(workspace),
    )
    env = render_environment(workspace) if profile == "full" else os.environ.copy()
    versions = runtime_versions(workspace, profile, plan["dataset"], env=env)
    artifacts = destination / profile
    if artifacts.exists():
        raise ValueError("Avaliação já existe; preserve os artefatos e use uma nova rodada.")
    artifacts.mkdir()
    (artifacts / "result").mkdir()
    config = config_for(destination, plan, profile)
    write(artifacts / "config.json", config)
    command = [
        str(workspace.evaluation_python),
        str(repo / spec["entrypoint"]),
        "--config",
        str(artifacts / "config.json"),
    ]
    if plan["dataset"] == "drdocbench-dev":
        command += ["--save_name", "benchmark"]
    env.update(
        {
            "HF_HOME": str(workspace.root / "data/.cache/huggingface-eval"),
            "XDG_CACHE_HOME": str(workspace.root / "data/.cache"),
            "MPLCONFIGDIR": str(workspace.root / "data/.cache/matplotlib"),
            "HF_HUB_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    metadata = {
        "profile": profile,
        "fixture": plan["fixture"],
        "evaluator": spec,
        "runtime_versions": versions,
        "benchmark_source_sha256": {
            path.relative_to(workspace.root).as_posix(): digest(path)
            for path in (workspace.root / "src/acessilia_benchmark").rglob("*.py")
        },
        "command": command,
        "predictions_sha256": hashes,
        "environment_lock_sha256": plan["environment_lock_sha256"],
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    write(artifacts / "execution.json", metadata)
    result = run_logged(
        command, artifacts / "evaluator.log", cwd=artifacts, env=env, timeout=timeout
    )
    metadata.update(
        seconds=result.seconds, returncode=result.returncode, timed_out=result.timed_out
    )
    metric_files = list((artifacts / "result").glob("*_metric_result.json"))
    metadata["status"] = (
        "ok"
        if result.returncode == 0 and not result.timed_out and len(metric_files) == 1
        else "failed"
    )
    write(artifacts / "execution.json", metadata)
    if metadata["status"] != "ok":
        seal(artifacts / "execution.json")
        raise ValueError(f"Avaliador falhou; consulte {artifacts / 'evaluator.log'}")
    try:
        load_plan(workspace, name)
        validate_predictions(destination, plan)
        metrics = read(metric_files[0])
        validate_metrics(artifacts, metrics)
        if profile == "full":
            validate_cdm(artifacts, metrics)
        summarize(destination, plan, artifacts, metrics, profile)
    except (ValueError, OSError, KeyError) as error:
        metadata.update(status="failed", error=str(error))
        write(artifacts / "execution.json", metadata)
        seal(artifacts / "execution.json")
        raise
    seal(artifacts / "execution.json")
    summary = read(artifacts / "summary.json")
    if summary.get("overall") is not None:
        print(f"Overall local: {summary['overall']:.4f}")
    print(f"Avaliação concluída → {artifacts / 'report.md'}")


def validate_metrics(artifacts, metrics):
    components = ("text_block", "table", "display_formula", "reading_order")
    for component in components:
        if not isinstance(metrics.get(component), dict) or not isinstance(
            metrics[component].get("all"), dict
        ):
            raise ValueError(f"Métricas oficiais incompletas: {component}")
        files = list((artifacts / "result").glob(f"*_{component}_result.json"))
        if len(files) != 1 or not isinstance(read(files[0]), list):
            raise ValueError(f"Pares de blocos oficiais ausentes/inválidos: {component}")


def validate_cdm(artifacts, metrics):
    """Official evaluators can return zero after missing runtime dependencies."""
    log = (artifacts / "evaluator.log").read_text(encoding="utf-8", errors="replace")
    failures = re.compile(
        r"Cannot find module|CDM sample failed|generated an exception|"
        r"File [`'][^\n]+\.(?:sty|cls)['`] not found|"
        r"font [^\n]+ cannot be found|magick: [^\n]*(?:not found|no decode delegate)",
        re.IGNORECASE,
    )
    if failures.search(log):
        raise ValueError("CDM contém falhas de execução/renderização; consulte evaluator.log.")
    formulas = list((artifacts / "result").glob("*_display_formula_result.json"))
    if formulas and read(formulas[0]) and "CDM" not in metrics["display_formula"]["all"]:
        raise ValueError("CDM ausente apesar de haver fórmulas pontuadas.")
    if formulas:
        required = sum(bool(str(row.get("gt", "")).strip()) for row in read(formulas[0]))
        rendered = list((artifacts / "result").glob("*/CDM/gt/bbox/*.jsonl"))
        if required and len(rendered) < required:
            raise ValueError(
                "CDM não renderizou todas as fórmulas de referência; resultado inválido."
            )
