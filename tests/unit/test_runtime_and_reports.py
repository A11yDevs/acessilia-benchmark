import sys
import time
from pathlib import Path

import fitz
import pytest
from PIL import Image

from acessilia_benchmark.adapters.acessilia import pack_images
from acessilia_benchmark.processes import run_logged
from acessilia_benchmark.services.doctor import interpreter_info, resolve_python


def test_virtual_environment_symlink_is_not_resolved(tmp_path, monkeypatch):
    candidate = tmp_path / ".venv/bin/python"
    candidate.parent.mkdir(parents=True)
    candidate.symlink_to(sys.executable)
    monkeypatch.setattr(
        "acessilia_benchmark.services.doctor.interpreter_info",
        lambda *_: {
            "modules": {name: True for name in ("agno", "fitz", "PIL", "fastapi", "docstruct")}
        },
    )
    selected, _ = resolve_python(tmp_path, candidate)
    assert selected == candidate
    assert selected != candidate.resolve()


def test_interpreter_probe_keeps_real_venv_prefix(tmp_path):
    info = interpreter_info(Path(sys.executable), tmp_path)
    assert info["prefix"] == sys.prefix


def test_empty_core_environment_has_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="Informe --python"):
        resolve_python(tmp_path, tmp_path / "missing/bin/python")


def test_timeout_stops_descendant_process(tmp_path):
    pid_file = tmp_path / "child.pid"
    child = "import time; time.sleep(30)"
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    result = run_logged([sys.executable, "-c", parent], tmp_path / "process.log", timeout=0.5)
    assert result.timed_out
    assert result.seconds < 5
    pid = int(pid_file.read_text())
    status = Path(f"/proc/{pid}/stat")
    for _ in range(20):
        if not status.exists() or status.read_text().split()[2] == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("Descendant remained running after timeout")


def test_pdf_embeds_original_jpeg_streams_without_recompression(tmp_path):
    images = [tmp_path / "first.jpg", tmp_path / "second.jpg"]
    for path, color in zip(images, ("red", "blue"), strict=True):
        with Image.new("RGB", (30, 40), color) as image:
            image.save(path, quality=92)
    target = tmp_path / "window.pdf"
    pack_images(images, target)
    with fitz.open(target) as document:
        assert len(document) == 2
        for page, original in zip(document, images, strict=True):
            xref = page.get_images()[0][0]
            assert document.extract_image(xref)["image"] == original.read_bytes()
