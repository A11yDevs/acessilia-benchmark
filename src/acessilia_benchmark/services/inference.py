"""Run Acessilia with validated requests, isolated storage and sealed evidence."""

import hashlib
import json
import os
from pathlib import Path

from ..adapters import acessilia
from ..core.runs import freeze_predictions, load_plan
from ..core.workspace import Workspace
from ..io import digest, local_path, read, seal, write
from ..processes import git, run_logged
from .doctor import resolve_python


def predict(
    workspace: Workspace, name: str, repo: Path, python: Path | None, timeout: float = 1800
) -> None:
    destination, plan = load_plan(workspace, name)
    if plan["fixture"]:
        raise ValueError("Rodada de autoverificação; crie outra para o Acessilia.")
    output = destination / "predictions"
    if output.exists():
        raise ValueError("Previsões já existem; crie outra rodada para evitar mistura.")
    repo = repo.expanduser().resolve()
    selected, interpreter = resolve_python(repo, python)
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
        "input_representation": "original image; lossless raster PDF for 2-page windows",
        "cache": "isolated Core storage; external provider caches follow server configuration",
        "mode": "normal",
        "pddl_execute_dry_run": False,
        "dependency_files": {
            path.name: digest(path)
            for path in (repo / "poetry.lock", repo / "uv.lock", repo / "pyproject.toml")
            if path.is_file()
        },
    }
    write(destination / "system.json", system)
    output.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "DATA_DIR": str(destination / "runtime/data"),
            "LOGS_DIR": str(destination / "runtime/logs"),
            "TEMP_DIR": str(destination / "runtime/tmp"),
            "PDDL_EXECUTE_DRY_RUN": "false",
        }
    )
    evidence = {"status": "running", "cases": [], "plan_sha256": digest(destination / "plan.json")}
    evidence_path = destination / "inference.json"
    write(evidence_path, evidence)
    completed = False
    try:
        with (destination / "timings.jsonl").open("w", encoding="utf-8") as timings:
            for case in plan["cases"]:
                target = local_path(output, case["prediction"])
                request = local_path(destination / "requests", case["prediction"] + ".json")
                log = local_path(destination / "logs", case["prediction"] + ".log")
                command = [
                    str(selected),
                    str(Path(acessilia.__file__).resolve()),
                    "--repo",
                    str(repo),
                    "--request",
                    str(request),
                    "--output",
                    str(target),
                ]
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
                    "seconds": result.seconds,
                }
                evidence["cases"].append(row)
                timings.write(json.dumps(row) + "\n")
                timings.flush()
                print(f"{status}: {case['id']} ({result.seconds:.1f}s)", flush=True)
        load_plan(workspace, name)
        completed = len(evidence["cases"]) == len(plan["cases"]) and all(
            case["status"] == "ok" for case in evidence["cases"]
        )
    finally:
        evidence["status"] = "ok" if completed else "failed"
        write(evidence_path, evidence)
        seal(evidence_path)
    if not completed:
        raise ValueError(
            "Inferência incompleta; consulte inference.json e logs. Não será pontuada."
        )
    freeze_predictions(destination, plan, {"kind": "acessilia", "label": system["commit"]})
