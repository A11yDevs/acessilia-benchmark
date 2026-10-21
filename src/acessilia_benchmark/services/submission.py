"""Package complete single-page Dr.DocBench test predictions for manual submission."""

import json
import zipfile
from pathlib import Path

from ..core.catalog import load_registry, verify
from ..core.runs import load_plan, validate_predictions
from ..core.sampling import ordered_cases
from ..io import digest, local_path, seal, write


def submit(workspace, name):
    destination, plan = load_plan(workspace, name)
    if plan["dataset"] != "drdocbench-test" or plan["fixture"]:
        raise ValueError("Submissão requer drdocbench-test real, sem referências.")
    if any(len(c["images"]) != 1 or len(c.get("page_numbers", [])) != 1 for c in plan["cases"]):
        raise ValueError("Submissão requer prepare --window-size 1; janelas não são separáveis.")
    snapshot = Path(plan["snapshot"])
    verify(plan["dataset"], load_registry(workspace)[plan["dataset"]], snapshot.parent.parent)
    expected = list(ordered_cases(workspace, plan["dataset"], snapshot.parent.parent, 42, 1))
    if {c["id"] for c in expected} != {c["id"] for c in plan["cases"]}:
        raise ValueError("Submissão requer todas as páginas do snapshot; amostra incompleta.")
    validate_predictions(destination, plan)
    output = destination / "submission"
    output.mkdir(exist_ok=False)
    rows = []
    for case in sorted(
        plan["cases"], key=lambda c: (c["subject"], c["document_id"], c["page_numbers"][0])
    ):
        rows.append(
            json.dumps(
                {
                    "subject": case["subject"],
                    "document_id": case["document_id"],
                    "page": case["page_numbers"][0],
                    "markdown": local_path(
                        destination / "predictions", case["prediction"]
                    ).read_text(encoding="utf-8"),
                },
                ensure_ascii=False,
            )
        )
    archive = output / "submission.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as stream:
        info = zipfile.ZipInfo("predictions.jsonl", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        stream.writestr(info, "\n".join(rows) + "\n")
    write(
        output / "manifest.json",
        {
            "pages": len(rows),
            "dataset_revision": plan["dataset_revision"],
            "plan_sha256": digest(destination / "plan.json"),
            "predictions_manifest_sha256": digest(destination / "prediction-manifest.json"),
            "submission_sha256": digest(archive),
            "uploaded": False,
        },
    )
    seal(output / "manifest.json")
    print(f"Pacote gerado, sem envio: {archive}")
    return archive
