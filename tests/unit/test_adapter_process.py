"""The Core interpreter can execute the adapter without installing the benchmark."""

import subprocess
import sys
from pathlib import Path

import pytest

from acessilia_benchmark import cli
from acessilia_benchmark.adapters import acessilia
from acessilia_benchmark.io import read, write


@pytest.mark.parametrize(
    "engine,use_cache,cache_hit,fail",
    [
        ("pipeline", True, None, None),
        ("structure", True, True, None),
        ("structure", False, False, None),
        ("structure", False, None, None),
        ("structure", False, True, "no_cache"),
        ("structure", False, False, "sdk failure"),
    ],
)
def test_adapter_executes_directly_in_isolated_interpreter(
    tmp_path, engine, use_cache, cache_hit, fail
):
    repo = tmp_path / "core"
    files = {
        "backend/config/settings.py": (
            "from types import SimpleNamespace\n"
            f"settings = SimpleNamespace(pipeline_engine='legacy', toolbox_use_remote_cache={use_cache!r})\n"
        ),
        "backend/service.py": (
            "async def process(source, mode):\n"
            "    return {'text': 'converted by Core', 'metadata': "
            "{'pddl_visual_failures': {'pictures': {'provider': 1}}, "
            "'pddl_extraction_degraded': True, "
            "'pddl_extraction_failures': {'mineru': 'TimeoutError'}, "
            "'pddl_toolbox_availability': {'mode': 'observe', 'applied': False}, "
            "'pddl_formula_diagnostics': {'status': 'degraded'}, "
            "'pddl_external_provider_limits': {'provider': 'docling-math'}}, "
            "'technical_warnings': ['visual failed']}\n"
        ),
        "libs/docstruct/src/docstruct/export/markdown.py": (
            "def document_to_markdown(document):\n    return document['text']\n"
        ),
    }
    if engine == "structure":
        files["backend/service.py"] = "raise AssertionError('full pipeline must not be imported')"
        files["scripts/bench/toolbox.py"] = (
            "raise AssertionError('Core helper bypasses cache policy')"
        )
        files["backend/tools/toolbox_client.py"] = (
            "def make_toolbox_client(cls, provider):\n"
            "    assert provider == 'docling'\n"
            "    return cls()\n"
        )
        files["libs/sdk/src/acessilia_sdk/toolbox/clients.py"] = (
            "from pathlib import Path\n"
            "class ToolboxStructureClient:\n"
            "    async def extract_structure(self, *, file_path, use_remote_cache):\n"
            f"        assert use_remote_cache is {use_cache!r}\n"
            "        assert file_path.is_file()\n"
            + (
                "        raise RuntimeError('sdk failure')\n"
                if fail == "sdk failure"
                else f"        return {{'text': 'converted by Core', 'provenance': {{'provider': 'docling', 'cache_hit': {cache_hit!r}, 'private_key': 'never-report'}}}}\n"
            )
            + "    async def close(self):\n"
            "        Path('client-closed').write_text('closed')\n"
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
    result = subprocess.run(
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
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if engine == "structure":
        assert (repo / "client-closed").read_text() == "closed"
    if fail:
        assert result.returncode != 0
        assert fail in result.stderr
        assert not output.exists()
        return
    assert result.returncode == 0, result.stderr
    assert output.read_text() == "converted by Core"
    metadata = read(output.with_suffix(".metadata.json"))
    assert metadata["mode"] == "normal"
    if engine == "pipeline":
        assert metadata["technical_warnings"] == ["visual failed"]
        assert metadata["processing_diagnostics"]["pddl_visual_failures"] == {
            "pictures": {"provider": 1}
        }
        assert metadata["processing_diagnostics"]["pddl_extraction_degraded"] is True
        assert metadata["processing_diagnostics"]["pddl_extraction_failures"] == {
            "mineru": "TimeoutError"
        }
        assert metadata["processing_diagnostics"]["pddl_toolbox_availability"] == {
            "mode": "observe",
            "applied": False,
        }
        assert metadata["processing_diagnostics"]["pddl_formula_diagnostics"] == {
            "status": "degraded"
        }
        assert metadata["processing_diagnostics"]["pddl_external_provider_limits"] == {
            "provider": "docling-math"
        }
    else:
        assert metadata["technical_warnings"] is None
        assert metadata["structure_execution"]["requested_use_remote_cache"] is use_cache
        assert metadata["structure_execution"]["provenance"]["cache_hit"] is cache_hit
        assert metadata["structure_execution"]["provenance"]["provider"] == "docling"
        assert "never-report" not in output.with_suffix(".metadata.json").read_text()


def test_render_tools_are_available_through_cli(workspace, monkeypatch):
    installed = []
    monkeypatch.setattr(cli.Workspace, "discover", lambda: workspace)
    monkeypatch.setattr(cli, "install_render_tools", installed.append)
    monkeypatch.setattr(sys, "argv", ["acessilia-benchmark", "setup-render-tools"])
    cli.main()
    assert installed == [workspace]
