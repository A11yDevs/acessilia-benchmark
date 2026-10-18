"""Install checksum-pinned rendering tools locally on Ubuntu 24.04 x86_64."""

import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from xml.sax.saxutils import escape

from ..core.workspace import Workspace
from ..io import digest, read


def environment(workspace: Workspace, base=None):
    """Discover optional local tools without mutating the parent process environment."""
    env = dict(os.environ if base is None else base)
    root = workspace.root / "data/tools"
    if (root / "bin/magick").is_file() and not shutil.which("magick", path=env.get("PATH", "")):
        env["PATH"] = str(root / "bin") + os.pathsep + env.get("PATH", "")
    texmf = root / "texlive/root/usr/share/texmf"
    if texmf.is_dir():
        env.setdefault("TEXMFHOME", str(texmf))
    tex = root / "texlive/root/usr/share/texlive/texmf-dist/tex"
    if tex.is_dir():
        prefix = str(tex) + "//"
        entries = env.get("TEXINPUTS", "").split(os.pathsep)
        if prefix not in entries:
            env["TEXINPUTS"] = os.pathsep.join([prefix, *entries])
    if (root / "fonts.conf").is_file():
        env.setdefault("FONTCONFIG_FILE", str(root / "fonts.conf"))
    env.setdefault("XDG_CACHE_HOME", str(workspace.root / "data/.cache"))
    return env


def install(workspace: Workspace) -> None:
    if platform.machine() != "x86_64" or not shutil.which("dpkg-deb"):
        raise ValueError("Instalador local requer Linux x86_64 com dpkg-deb.")
    root = workspace.root / "data/tools"
    lock = read(workspace.root / "evaluation/render-tools.lock.json")
    for item in lock["artifacts"]:
        target = root / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or digest(target) != item["sha256"]:
            temporary = target.with_suffix(target.suffix + ".download")
            try:
                with urllib.request.urlopen(item["url"], timeout=120) as response:
                    with temporary.open("wb") as output:
                        shutil.copyfileobj(response, output)
                if digest(temporary) != item["sha256"]:
                    raise ValueError(f"Checksum inválido: {item['path']}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if item["kind"] == "appimage":
            target.chmod(0o755)
            if not (target.parent / "squashfs-root/AppRun").is_file():
                subprocess.run([str(target), "--appimage-extract"], cwd=target.parent, check=True)
        elif item["kind"] == "deb":
            subprocess.run(["dpkg-deb", "-x", str(target), str(root / "texlive/root")], check=True)
        elif item["kind"] == "node":
            dependency = workspace.root / (
                "vendor/DrDocBench/metrics/cdm/modules/tokenize_latex/third_party/match-at"
            )
            if not (dependency / "package.json").is_file():
                raise ValueError(
                    "Execute acessilia-benchmark setup antes de instalar render tools."
                )
            with tarfile.open(target) as archive:
                source = archive.extractfile("package/lib/matchAt.js")
                if source is None:
                    raise ValueError("Pacote match-at incompleto.")
                module = dependency / "lib/matchAt.js"
                module.parent.mkdir(exist_ok=True)
                module.write_bytes(source.read())
    binary = root / "bin/magick"
    binary.parent.mkdir(exist_ok=True)
    if binary.is_symlink():
        binary.unlink()
    if binary.exists():
        raise ValueError(f"Preserve o arquivo existente antes de instalar: {binary}")
    binary.symlink_to("../imagemagick/squashfs-root/AppRun")
    fonts, cache = (
        escape(str(root / "fonts")),
        escape(str(workspace.root / "data/.cache/fontconfig")),
    )
    (root / "fonts.conf").write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
        '<fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        f"<dir>{fonts}</dir><cachedir>{cache}</cachedir></fontconfig>\n",
        encoding="utf-8",
    )
    print("Render tools preparados; detectados automaticamente em avaliações full.")
