"""Deterministic stratified page and window selection."""

import hashlib
from collections import defaultdict, deque
from pathlib import Path

from ..io import read
from .catalog import load_registry
from .workspace import Workspace


def ordered_cases(workspace: Workspace, dataset, data_dir, seed):
    """Stable stratification by source type (Omni) or subject (Dr), no GT scores."""
    spec = load_registry(workspace)[dataset]
    snapshot = data_dir / dataset / spec["revision"]
    groups = defaultdict(list)
    if dataset == "omnidocbench":
        for page in read(snapshot / "OmniDocBench.json"):
            info = page["page_info"]
            image = snapshot / "images" / Path(info["image_path"]).name
            case = {
                "id": image.stem,
                "images": [str(image)],
                "prediction": image.stem + ".md",
                "reference_pages": [page],
            }
            group = str(info.get("page_attribute", {}).get("data_source", "unknown"))
            groups[group].append(case)
    else:
        for folder in sorted((snapshot / "dev").glob("*/*")):
            if not folder.is_dir():
                continue
            subject, doc = (folder.parent.name, folder.name)
            pages = sorted(
                folder.glob("images/page_*.jpg"), key=lambda path: int(path.stem.split("_")[-1])
            )
            for first, second in zip(pages, pages[1:], strict=False):
                start, end = (int(first.stem.split("_")[-1]), int(second.stem.split("_")[-1]))
                if end != start + 1:
                    continue
                refs = [folder / "json" / f"{doc}_page_{n}.json" for n in (start, end)]
                if not any(read(ref) for ref in refs):
                    continue
                name = f"{doc}_page_{start}-{end}"
                groups[subject].append(
                    {
                        "id": f"{subject}/{name}",
                        "images": [str(first), str(second)],
                        "prediction": f"{subject}/{name}.md",
                        "references": [str(ref) for ref in refs],
                        "reference_markdown": [
                            str(folder / "mds" / f"{doc}_{n}.md") for n in (start, end)
                        ],
                    }
                )
    queues = []
    for group in sorted(
        groups, key=lambda name: hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()
    ):
        entries = sorted(
            groups[group],
            key=lambda case: hashlib.sha256(f"{seed}:{case['id']}".encode()).hexdigest(),
        )
        queues.append(deque(entries))
    while any(queues):
        for queue in queues:
            if queue:
                yield queue.popleft()
