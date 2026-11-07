"""Run Acessilia with validated requests, isolated storage and sealed evidence."""

import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path

from ..adapters import acessilia
from ..core.runs import freeze_predictions, load_plan
from ..core.workspace import Workspace
from ..io import digest, local_path, read, seal, verify_seal, write
from ..processes import git, run_logged
from ..reporting import summarize_runtime
from .doctor import resolve_python
from .toolbox import check_toolbox, read_toolbox_settings


def predict(
    workspace: Workspace,
    name: str,
    repo: Path,
    python: Path | None,
    timeout: float = 1800,
    *,
    engine: str = "pipeline",
    provider: str | None = None,
    resume: bool = False,
) -> None:
    destination, _ = load_plan(workspace, name)
    with (destination / ".inference.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Outra inferência está usando esta rodada.") from error
        _predict(workspace, name, repo, python, timeout, engine, provider, resume)


def _predict(workspace, name, repo, python, timeout, engine, provider, resume):
    if engine not in {"pipeline", "structure"} or (provider and engine != "structure"):
        raise ValueError("Provider explícito requer --engine structure.")
    if engine == "structure" and not provider:
        raise ValueError("Engine structure requer --provider.")
    if timeout <= 0:
        raise ValueError("Timeout deve ser positivo.")
    destination, plan = load_plan(workspace, name)
    if engine == "structure" and any(len(case["images"]) != 1 for case in plan["cases"]):
        raise ValueError("Engine structure requer casos de uma página; prepare --window-size 1.")
    if plan["fixture"]:
        raise ValueError("Rodada de autoverificação; crie outra para o Acessilia.")
    output = destination / "predictions"
    if output.exists() and not resume:
        raise ValueError("Previsões já existem; crie outra rodada para evitar mistura.")
    repo = repo.expanduser().resolve()
    selected, interpreter = resolve_python(repo, python)
    toolbox_settings = read_toolbox_settings(selected, repo)
    selected_providers = toolbox_settings.providers if engine == "pipeline" else (provider,)
    pinned_providers = toolbox_settings.pinned_providers if engine == "pipeline" else ()
    toolbox = check_toolbox(
        toolbox_settings.endpoints,
        selected_providers,
        toolbox_settings.api_key,
        pinned_providers,
    )
    if not toolbox["ok"]:
        failed_providers = [
            provider for provider, status in toolbox["providers"].items() if not status["ok"]
        ]
        detail = (
            " providers sem saúde: " + ", ".join(failed_providers)
            if failed_providers
            else " API Toolbox indisponível"
        )
        raise ValueError("Pré-verificação Toolbox falhou; execute doctor para detalhes." + detail)
    for case in plan["cases"]:
        request = local_path(destination / "requests", case["prediction"] + ".json")
        if read(request) != {"id": case["id"], "images": case["images"]}:
            raise ValueError(f"Request alterado: {case['id']}")
    system = {
        "repo": str(repo),
        "commit": git(repo, "rev-parse", "HEAD"),
        "dirty": bool(git(repo, "status", "--porcelain")),
        "diff_sha256": hashlib.sha256(git(repo, "diff", "HEAD").encode()).hexdigest(),
        "python": str(selected),
        "interpreter": interpreter,
        "toolbox_runtime": toolbox["identity"],
        "input_representation": "original image; lossless raster PDF for 2-page windows",
        "cache": "isolated Core storage; external provider caches follow server configuration",
        "mode": "normal",
        "engine": engine,
        "provider": provider,
        "adapter_sha256": digest(Path(acessilia.__file__)),
        "source_sha256": {
            path.relative_to(repo).as_posix(): digest(path)
            for folder in ("backend", "libs", "scripts")
            for path in sorted((repo / folder).rglob("*.py"))
            if not any(
                part.startswith(".") or part == "__pycache__"
                for part in path.relative_to(repo).parts
            )
        },
        "configuration_sha256": {
            path.name: digest(path) for path in sorted(repo.glob(".env*")) if path.is_file()
        },
        "environment_sha256": hashlib.sha256(
            json.dumps(
                {
                    k: v
                    for k, v in os.environ.items()
                    if k.startswith(("TOOLBOX_", "PDDL_", "OPENROUTER_", "OLLAMA_", "AI_"))
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "pddl_execute_dry_run": False,
        "dependency_files": {
            path.name: digest(path)
            for path in (repo / "poetry.lock", repo / "uv.lock", repo / "pyproject.toml")
            if path.is_file()
        },
    }
    evidence_path = destination / "inference.json"
    previous = {}
    attempt = 1
    if resume:
        verify_seal(evidence_path)
        evidence = read(evidence_path)
        if evidence.get("plan_sha256") != digest(destination / "plan.json"):
            raise ValueError("Inferência pertence a outro plano.")
        if read(destination / "system.json") != system:
            raise ValueError("Core, ambiente ou configuração mudou; prepare outra rodada.")
        if evidence.get("system_sha256") != digest(destination / "system.json"):
            raise ValueError("Evidência de sistema alterada.")
        rows = evidence["cases"]
        if [
            json.loads(line) for line in (destination / "timings.jsonl").read_text().splitlines()
        ] != rows:
            raise ValueError("Tempos divergentes da inferência.")
        previous = {row["id"]: row for row in rows}
        if len(previous) != len(rows) or not previous.keys() <= {c["id"] for c in plan["cases"]}:
            raise ValueError("Casos de inferência inválidos.")
        for case in plan["cases"]:
            row = previous.get(case["id"], {})
            if row.get("status") == "ok":
                target = local_path(output, case["prediction"])
                if digest(target) != row.get("prediction_sha256"):
                    raise ValueError(f"Previsão alterada: {case['id']}")
                metadata = target.with_suffix(".metadata.json")
                if (digest(metadata) if metadata.is_file() else None) != row.get("metadata_sha256"):
                    raise ValueError(f"Metadados alterados: {case['id']}")
        if (destination / "prediction-manifest.json").exists():
            from ..core.runs import validate_predictions

            validate_predictions(destination, plan)
            print("Rodada já concluída e validada; nenhuma inferência repetida.")
            return
        attempt = evidence.get("attempt", 1) + 1
        archive = destination / "attempts" / str(attempt - 1)
        archive.mkdir(parents=True, exist_ok=False)
        for filename in ("inference.json", "inference.json.sha256", "timings.jsonl"):
            shutil.copyfile(destination / filename, archive / filename)
    else:
        if evidence_path.exists():
            raise ValueError("Inferência já iniciada; use --resume.")
        write(destination / "system.json", system)
    output.mkdir(exist_ok=resume)
    environment = os.environ.copy()
    environment.update(
        {
            "DATA_DIR": str(destination / "runtime/data"),
            "LOGS_DIR": str(destination / "runtime/logs"),
            "TEMP_DIR": str(destination / "runtime/tmp"),
            "PDDL_EXECUTE_DRY_RUN": "false",
        }
    )
    evidence = {
        "status": "running",
        "cases": list(previous.values()),
        "plan_sha256": digest(destination / "plan.json"),
        "system_sha256": digest(destination / "system.json"),
        "attempt": attempt,
    }
    write(evidence_path, evidence)
    completed = False

    def checkpoint():
        write(evidence_path, evidence)
        seal(evidence_path)
        (destination / "timings.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in evidence["cases"]), encoding="utf-8"
        )

    checkpoint()
    try:
        for case in plan["cases"]:
            if previous.get(case["id"], {}).get("status") == "ok":
                continue
            target = local_path(output, case["prediction"])
            request = local_path(destination / "requests", case["prediction"] + ".json")
            log = local_path(destination / "logs" / str(attempt), case["prediction"] + ".log")
            command = [
                str(selected),
                str(Path(acessilia.__file__).resolve()),
                "--repo",
                str(repo),
                "--request",
                str(request),
                "--output",
                str(target),
                "--engine",
                engine,
            ]
            if provider:
                command += ["--provider", provider]
            target.unlink(missing_ok=True)
            target.with_suffix(".metadata.json").unlink(missing_ok=True)
            result = run_logged(command, log, timeout=timeout, env=environment)
            status = (
                "timeout"
                if result.timed_out
                else "ok"
                if result.returncode == 0 and target.is_file()
                else "failed"
            )
            if status != "ok":
                target.unlink(missing_ok=True)
                target.with_suffix(".metadata.json").unlink(missing_ok=True)
            row = {
                "id": case["id"],
                "pages": len(case["images"]),
                "status": status,
                "returncode": result.returncode,
                "seconds": previous.get(case["id"], {}).get("seconds", 0) + result.seconds,
                "attempts": previous.get(case["id"], {}).get("attempts", 0) + 1,
                "failed_attempts": previous.get(case["id"], {}).get("failed_attempts", 0)
                + int(status != "ok"),
                "failure_kind": _classify_failure(log, result.timed_out)
                if status != "ok"
                else None,
                "failure_kinds": _accumulate_failure_kinds(
                    previous.get(case["id"], {}),
                    _classify_failure(log, result.timed_out) if status != "ok" else None,
                ),
                "prediction_sha256": digest(target) if status == "ok" else None,
                "metadata_sha256": digest(target.with_suffix(".metadata.json"))
                if status == "ok" and target.with_suffix(".metadata.json").is_file()
                else None,
            }
            previous[case["id"]] = row
            evidence["cases"] = list(previous.values())
            checkpoint()
            print(f"{status}: {case['id']} ({result.seconds:.1f}s)", flush=True)
        load_plan(workspace, name)
        completed = len(evidence["cases"]) == len(plan["cases"]) and all(
            case["status"] == "ok" for case in evidence["cases"]
        )
    finally:
        evidence["status"] = "ok" if completed else "failed"
        checkpoint()
        summarize_runtime(destination, plan)
    if not completed:
        raise ValueError(
            "Inferência incompleta; consulte inference.json e logs. Não será pontuada."
        )
    freeze_predictions(destination, plan, {"kind": "acessilia", "label": system["commit"]})


def _classify_failure(log: Path, timed_out: bool) -> str:
    """Classify failures by fixed signatures without persisting raw log text."""
    if timed_out:
        return "benchmark_timeout"
    try:
        content = log.read_text(encoding="utf-8", errors="replace").casefold()
    except OSError:
        return "process_failed"
    if any(
        marker in content
        for marker in (
            "toolboxtimeout",
            "providertimeouterror",
            "timeout do provedor",
            "provider timeout",
            "gateway deadline",
        )
    ):
        return "provider_timeout"
    if any(
        marker in content
        for marker in (
            "toolboxunavailable",
            "providerunavailableerror",
            "provider unavailable",
            "toolbox unavailable",
            "provedor indisponível",
            "provedor indisponivel",
        )
    ):
        return "provider_unavailable"
    return "process_failed"


def _accumulate_failure_kinds(previous: dict, failure_kind: str | None) -> dict:
    """Retain category counts across resumes and ignore unknown historical keys."""
    allowed = {"benchmark_timeout", "provider_timeout", "provider_unavailable", "process_failed"}
    previous_kinds = previous.get("failure_kinds")
    legacy = not isinstance(previous_kinds, dict)
    if legacy:
        previous_kinds = {}
    counts = {
        kind: value
        for kind, value in previous_kinds.items()
        if kind in allowed and isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }
    legacy_failures = previous.get("failed_attempts", 0)
    if legacy and isinstance(legacy_failures, int) and not isinstance(legacy_failures, bool):
        legacy_failures = max(0, legacy_failures)
        if previous.get("status") == "timeout":
            if legacy_failures > 0:
                counts["benchmark_timeout"] = 1
                legacy_failures -= 1
        if legacy_failures > 0:
            counts["process_failed"] = legacy_failures
    if failure_kind:
        counts[failure_kind] = counts.get(failure_kind, 0) + 1
    return counts
