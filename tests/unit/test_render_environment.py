import os

from acessilia_benchmark.services.render_tools import environment


def local_tools(workspace):
    root = workspace.root / "data/tools"
    magick = root / "bin/magick"
    magick.parent.mkdir(parents=True)
    magick.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    magick.chmod(0o755)
    (root / "texlive/root/usr/share/texmf").mkdir(parents=True)
    (root / "texlive/root/usr/share/texlive/texmf-dist/tex").mkdir(parents=True)
    (root / "fonts.conf").write_text("<fontconfig/>", encoding="utf-8")
    return root


def test_local_render_tools_are_discovered_without_mutating_parent_environment(workspace):
    root = local_tools(workspace)
    parent = dict(os.environ)
    base = {"PATH": "/nonexistent", "TEXINPUTS": "/custom/tex:"}
    result = environment(workspace, base)
    assert base == {"PATH": "/nonexistent", "TEXINPUTS": "/custom/tex:"}
    assert dict(os.environ) == parent
    assert result["PATH"].split(os.pathsep)[0] == str(root / "bin")
    assert result["TEXMFHOME"] == str(root / "texlive/root/usr/share/texmf")
    assert result["FONTCONFIG_FILE"] == str(root / "fonts.conf")
    assert result["TEXINPUTS"].endswith(":/custom/tex:")


def test_explicit_tools_fonts_and_cache_are_preserved_and_discovery_is_idempotent(workspace):
    root = local_tools(workspace)
    base = {
        "PATH": str(root / "bin"),
        "TEXMFHOME": "/custom/texmf",
        "FONTCONFIG_FILE": "/custom/fonts.conf",
        "XDG_CACHE_HOME": "/custom/cache",
    }
    first = environment(workspace, base)
    assert all(first[key] == value for key, value in base.items())
    assert environment(workspace, first) == first
    assert first["TEXINPUTS"].endswith(":")  # Preserve default kpathsea search paths.


def test_missing_local_installation_keeps_host_tools_available(workspace):
    result = environment(workspace, {"PATH": "/usr/bin"})
    assert result["PATH"] == "/usr/bin"
    assert "FONTCONFIG_FILE" not in result
    assert "TEXMFHOME" not in result
    assert "TEXINPUTS" not in result
