"""Workspace discovery must survive package reorganization."""

from pathlib import Path

from acessilia_benchmark.core.workspace import Workspace


def test_discover_checkout_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACESSILIA_BENCHMARK_WORKSPACE", raising=False)
    repository = Path(__file__).resolve().parents[2]
    assert Workspace.discover().root == repository


def test_explicit_workspace_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("ACESSILIA_BENCHMARK_WORKSPACE", str(tmp_path))
    assert Workspace.discover().root == tmp_path
