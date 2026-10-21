"""The Core interpreter can execute the adapter without installing the benchmark."""

import subprocess
import sys
from pathlib import Path

from acessilia_benchmark import cli
from acessilia_benchmark.adapters import acessilia
from acessilia_benchmark.io import read, write


def test_adapter_executes_directly_in_isolated_interpreter(tmp_path):
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
