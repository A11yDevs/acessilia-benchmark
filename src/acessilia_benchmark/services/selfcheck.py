"""Reference-based infrastructure checks, never model performance."""

from pathlib import Path

from ..core.runs import freeze_predictions, prepare
from ..core.workspace import Workspace
from ..io import local_path, read
from .evaluation import evaluate


def smoke(workspace: Workspace, dataset, name, data_dir, window_size=2):
    destination, plan = prepare(
        workspace, dataset, name, data_dir, 10, 42, fixture=True, window_size=window_size
    )
    pages = read(destination / "ground-truth.json") if dataset == "omnidocbench" else None
    for index, case in enumerate(plan["cases"]):
        if pages is None:
            content = "\n\n".join(Path(path).read_text() for path in case["reference_markdown"])
        else:
            blocks = sorted(
                (
                    block
                    for block in pages[index]["layout_dets"]
                    if not block.get("ignore") and block.get("order") is not None
                ),
                key=lambda block: block["order"],
            )
            parts = []
            for block in blocks:
                if block["category_type"] == "table":
                    parts.append(block.get("html") or block.get("latex") or "")
                elif block["category_type"] == "equation_isolated":
                    formula = block.get("latex") or block.get("text") or ""
                    parts.append(
                        formula if formula.startswith(("$", "\\[")) else "$$\n" + formula + "\n$$"
                    )
                else:
                    parts.append(block.get("text") or "")
            content = "\n\n".join(parts)
        target = local_path(destination / "predictions", case["prediction"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    freeze_predictions(
        destination, plan, {"kind": "selfcheck", "label": "references, not model inference"}
    )
    evaluate(workspace, name, "basic")
