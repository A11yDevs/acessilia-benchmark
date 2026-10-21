"""Create immutable evaluation plans and validate artifacts."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from ..io import digest, local_path, read, seal, verify_seal, write
from .catalog import load_registry, verify
from .sampling import ordered_cases
from .workspace import Workspace


def prepare(
    workspace: Workspace, dataset, name, data_dir, limit, seed, fixture=False, window_size=2
):
    destination = workspace.run_dir(name)
    if destination.exists():
        raise ValueError("Rodada já existe; escolha outro nome para preservar os resultados.")
    if fixture and load_registry(workspace)[dataset]["evaluator"] is None:
        raise ValueError("Dataset sem referências; smoke indisponível. Use prepare e predict.")
    verify(dataset, load_registry(workspace)[dataset], data_dir)
    cases = list(ordered_cases(workspace, dataset, data_dir, seed, window_size))
    if fixture:

        def categories(case):
            pages = case.get("reference_pages")
            if pages is None:
                pages = [page for path in case["references"] for page in read(Path(path))]
            return {block["category_type"] for page in pages for block in page["layout_dets"]}

        chosen = {}
        for category in ("equation_isolated", "table", "text_block"):
            match = next((case for case in cases if category in categories(case)), None)
            if match is None:
                raise ValueError(f"Autoverificação não encontrou {category} no dataset.")
            chosen[match["id"]] = match
        for case in cases:
            if len(chosen) >= limit:
                break
            chosen[case["id"]] = case
        cases = list(chosen.values())
    elif limit:
        cases = cases[:limit]
    if not cases:
        raise ValueError("Amostra vazia.")
    predictions = [case["prediction"] for case in cases]
    if len(predictions) != len(set(predictions)):
        raise ValueError("Colisão de nomes de previsões.")
    destination.mkdir(parents=True)
    if dataset == "omnidocbench":
        pages = [case.pop("reference_pages")[0] for case in cases]
        write(destination / "ground-truth.json", pages)
        references = [str(destination / "ground-truth.json")]
    else:
        references = sorted({path for case in cases for path in case["references"]})
    inputs = sorted({image for case in cases for image in case["images"]})
    snapshot = data_dir / dataset / load_registry(workspace)[dataset]["revision"]
    plan = {
        "schema_version": 2,
        "dataset": dataset,
        "dataset_revision": load_registry(workspace)[dataset]["revision"],
        "snapshot": str(snapshot),
        "seed": seed,
        "window_size": 1 if dataset == "omnidocbench" else window_size,
        "limit": limit,
        "fixture": fixture,
        "cases": cases,
        "unique_pages": len(inputs),
        "windows": len(cases),
        "evaluator": load_registry(workspace)[dataset]["evaluator"],
        "environment_lock_sha256": digest(workspace.root / "evaluation/uv.lock"),
        "created_at": datetime.now(UTC).isoformat(),
        "input_sha256": {path: digest(Path(path)) for path in inputs},
        "reference_sha256": {path: digest(Path(path)) for path in references},
    }
    write(destination / "plan.json", plan)
    seal(destination / "plan.json")
    for case in cases:
        write(
            local_path(destination / "requests", case["prediction"] + ".json"),
            {"id": case["id"], "images": case["images"]},
        )
    print(f"Rodada {name}: {len(cases)} casos, {len(inputs)} páginas únicas → {destination}")
    return (destination, plan)


def load_plan(workspace: Workspace, name):
    destination = workspace.run_dir(name)
    plan = read(destination / "plan.json")
    if plan.get("schema_version") != 2:
        raise ValueError(
            "Rodada antiga; preserve os relatórios e prepare uma nova rodada (schema 2)."
        )
    verify_seal(destination / "plan.json")
    if not isinstance(plan.get("fixture"), bool) or not plan.get("cases"):
        raise ValueError("Plano inválido: fixture/casos.")
    if len({case["id"] for case in plan["cases"]}) != len(plan["cases"]):
        raise ValueError("IDs de casos duplicados.")
    for case in plan["cases"]:
        local_path(destination / "predictions", case["prediction"])
    if plan["evaluator"] != load_registry(workspace)[plan["dataset"]]["evaluator"]:
        raise ValueError("A configuração do avaliador mudou desde a preparação.")
    if plan["environment_lock_sha256"] != digest(workspace.root / "evaluation/uv.lock"):
        raise ValueError("O lock Python mudou desde a preparação.")
    for field in ("input_sha256", "reference_sha256"):
        for path, expected in plan[field].items():
            if not Path(path).is_file() or digest(Path(path)) != expected:
                raise ValueError(f"Entrada/referência alterada: {path}")
    return (destination, plan)


def prediction_hashes(folder, plan):
    expected = {case["prediction"] for case in plan["cases"]}
    actual = {path.relative_to(folder).as_posix() for path in folder.rglob("*.md")}
    missing, extra = (expected - actual, actual - expected)
    if missing or extra:
        raise ValueError(
            f"Cobertura inválida: {len(missing)} ausentes, {len(extra)} extras; exemplos: {sorted(missing)[:3]} / {sorted(extra)[:3]}"
        )
    return {name: digest(local_path(folder, name)) for name in sorted(expected)}


def freeze_predictions(destination, plan, origin):
    hashes = prediction_hashes(destination / "predictions", plan)
    evidence = {
        name: digest(destination / name)
        for name in ("system.json", "inference.json", "timings.jsonl")
        if (destination / name).is_file()
    }
    metadata = {
        path.relative_to(destination / "predictions").as_posix(): digest(path)
        for path in (destination / "predictions").rglob("*.metadata.json")
    }
    manifest = {
        "schema_version": 1,
        "plan_sha256": digest(destination / "plan.json"),
        "origin": origin,
        "files": hashes,
        "evidence": evidence,
        "metadata": metadata,
    }
    write(destination / "prediction-manifest.json", manifest)
    seal(destination / "prediction-manifest.json")


def validate_predictions(destination, plan):
    path = destination / "prediction-manifest.json"
    verify_seal(path)
    manifest = read(path)
    if manifest.get("plan_sha256") != digest(destination / "plan.json"):
        raise ValueError("Previsões pertencem a outro plano.")
    hashes = prediction_hashes(destination / "predictions", plan)
    if hashes != manifest["files"]:
        raise ValueError("Previsões alteradas após inferência/importação.")
    origin = manifest.get("origin", {}).get("kind")
    expected_origin = "selfcheck" if plan["fixture"] else ("acessilia", "imported")
    if origin not in ((expected_origin,) if isinstance(expected_origin, str) else expected_origin):
        raise ValueError("Origem das previsões incompatível com a rodada.")
    for name, expected in manifest.get("evidence", {}).items():
        if digest(local_path(destination, name)) != expected:
            raise ValueError(f"Evidência de inferência alterada: {name}")
    for name, expected in manifest.get("metadata", {}).items():
        if digest(local_path(destination / "predictions", name)) != expected:
            raise ValueError(f"Metadados de inferência alterados: {name}")
    if origin == "acessilia":
        verify_seal(destination / "inference.json")
        evidence = read(destination / "inference.json")
        ids = [row["id"] for row in evidence["cases"]]
        expected = {case["id"] for case in plan["cases"]}
        if evidence["status"] != "ok" or set(ids) != expected or len(ids) != len(expected):
            raise ValueError("Inferência incompleta ou duplicada.")
        if any(row["status"] != "ok" for row in evidence["cases"]):
            raise ValueError("Inferência contém falhas.")
    return hashes


def import_predictions(workspace, name, source, label):
    destination, plan = load_plan(workspace, name)
    if plan["fixture"]:
        raise ValueError("Não importe previsões em uma autoverificação.")
    prediction_hashes(source, plan)
    output = destination / "predictions"
    if output.exists():
        raise ValueError("Previsões já existem; prepare outra rodada.")
    for case in plan["cases"]:
        target = local_path(output, case["prediction"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path(source, case["prediction"]), target)
    freeze_predictions(destination, plan, {"kind": "imported", "label": label})
