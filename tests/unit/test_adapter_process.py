"""The Core interpreter can execute the adapter without installing the benchmark."""

import subprocess
import sys
from pathlib import Path

import pytest

from acessilia_benchmark import cli
from acessilia_benchmark.adapters import acessilia
from acessilia_benchmark.io import read, write


@pytest.mark.parametrize("engine", ["pipeline", "structure"])
def test_adapter_executes_directly_in_isolated_interpreter(tmp_path, engine):
    repo = tmp_path / "core"
    files = {
        "backend/config/settings.py": (
            "from types import SimpleNamespace\n"
            "settings = SimpleNamespace(pipeline_engine='legacy')\n"
        ),
        "backend/service.py": (
            "async def process(source, mode):\n"
            "    return {'text': 'converted by Core', 'metadata': {}}\n"
        ),
        "libs/docstruct/src/docstruct/export/markdown.py": (
            "def document_to_markdown(document):\n    return document['text']\n"
        ),
    }
    if engine == "structure":
        files["backend/service.py"] = "raise AssertionError('full pipeline must not be imported')"
        files["scripts/bench/toolbox.py"] = (
            "def extract_structure(source, provider):\n"
            "    assert provider == 'docling'\n"
            "    return {'text': 'converted by Core'}\n"
        )
        files["scripts/bench/core.py"] = "def payload_to_canonical(payload):\n    return payload\n"
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    image = tmp_path / "page.png"
    image.write_bytes(b"fixture; image processing is stubbed in Core")
    request = tmp_path / "request.json"
    write(request, {"id": "page", "images": [str(image)]})
    output = tmp_path / "prediction.md"
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(Path(acessilia.__file__).resolve()),
            "--repo",
            str(repo),
            "--request",
            str(request),
            "--output",
            str(output),
            "--engine",
            engine,
            *(["--provider", "docling"] if engine == "structure" else []),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert output.read_text() == "converted by Core"
    assert read(output.with_suffix(".metadata.json"))["mode"] == "normal"


def test_render_tools_are_available_through_cli(workspace, monkeypatch):
    installed = []
    monkeypatch.setattr(cli.Workspace, "discover", lambda: workspace)
    monkeypatch.setattr(cli, "install_render_tools", installed.append)
    monkeypatch.setattr(sys, "argv", ["acessilia-benchmark", "setup-render-tools"])
    cli.main()
    assert installed == [workspace]
