"""Small self-contained datasets; no downloaded corpus or providers for unit tests."""

from pathlib import Path

import pytest
from PIL import Image

from acessilia_benchmark.core.workspace import Workspace
from acessilia_benchmark.io import digest, read, write

REPOSITORY = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption(
        "--run-full",
        action="store_true",
        default=False,
        help="Run official full integration checks, including CDM (requires prepared datasets/runtime).",
    )


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "evaluation/uv.lock").write_text("frozen environment", encoding="utf-8")
    write(tmp_path / "datasets/registry.json", {"schema_version": 1, "datasets": {}})
    return Workspace(tmp_path)


@pytest.fixture
def dataset_factory(workspace):
    def build(name="omnidocbench"):
        snapshot = workspace.data / name / "fixture"
        if name == "omnidocbench":
            pages = []
            for index, category in enumerate(("text_block", "table", "equation_isolated")):
                image = snapshot / f"images/page-{index}.png"
                image.parent.mkdir(parents=True, exist_ok=True)
                with Image.new("RGB", (20, 30), "white") as frame:
                    frame.save(image)
                pages.append(
                    {
                        "page_info": {
                            "image_path": image.name,
                            "page_attribute": {"data_source": "book"},
                        },
                        "layout_dets": [
                            {"category_type": category, "order": 0, "text": "reference"}
                        ],
                    }
                )
            write(snapshot / "OmniDocBench.json", pages)
        else:
            for number in (2, 3, 9, 10, 11, 20):
                split = "test" if name == "drdocbench-test" else "dev"
                doc = snapshot / split / "DOMAIN/document"
                image = doc / f"images/page_{number}.jpg"
                image.parent.mkdir(parents=True, exist_ok=True)
                with Image.new("RGB", (20, 30), "white") as frame:
                    frame.save(image)
                if name == "drdocbench-test":
                    continue
                write(
                    doc / f"json/document_page_{number}.json",
                    [
                        {
                            "layout_dets": [
                                {"category_type": "text_block", "order": 0, "text": "reference"}
                            ]
                        }
                    ],
                )
                markdown = doc / f"mds/document_{number}.md"
                markdown.parent.mkdir(parents=True, exist_ok=True)
                markdown.write_text("reference", encoding="utf-8")
        files = [
            {
                "path": path.relative_to(snapshot).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in sorted(snapshot.rglob("*"))
            if path.is_file()
        ]
        spec = {
            "evaluator": read(REPOSITORY / "datasets/registry.json")["datasets"][name]["evaluator"],
            "repo_id": "test/dataset",
            "revision": "fixture",
            "split": "test" if name == "drdocbench-test" else "dev",
            "source": "https://example.invalid/dataset",
            "expected_files": len(files),
            "expected_bytes": sum(file["bytes"] for file in files),
        }
        catalog = read(workspace.root / "datasets/registry.json")
        catalog["datasets"][name] = spec
        write(workspace.root / "datasets/registry.json", catalog)
        write(
            snapshot / "download-manifest.json",
            {
                "schema_version": 1,
                "dataset_id": name,
                "repo_id": spec["repo_id"],
                "revision": "fixture",
                "split": "test" if name == "drdocbench-test" else "dev",
                "files": files,
            },
        )
        return snapshot, spec

    return build
