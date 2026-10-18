"""A fresh checkout resolves dependencies; later setups preserve that resolution."""

from acessilia_benchmark.io import write
from acessilia_benchmark.services import runtime


def test_setup_generates_then_preserves_local_lock(workspace, monkeypatch):
    write(workspace.root / "datasets/registry.json", {"schema_version": 1, "datasets": {}})
    lock = workspace.root / "evaluation/uv.lock"
    lock.unlink()
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/bin/uv")
    commands = []

    def sync(command, *, check, env):
        assert check
        commands.append(command)
        lock.write_text("resolved dependencies", encoding="utf-8")

    monkeypatch.setattr(runtime.subprocess, "run", sync)
    runtime.setup(workspace)
    runtime.setup(workspace)

    assert "--frozen" not in commands[0]
    assert commands[1] == [*commands[0], "--frozen"]
    assert commands[0][-2:] == ["--python", runtime.EVALUATION_PYTHON_VERSION]
    assert not (workspace.root / "evaluation/.python-version").exists()


def test_evaluator_uses_configuration_from_dataset_catalog(workspace, dataset_factory, monkeypatch):
    _, spec = dataset_factory()
    expected = spec["evaluator"]
    repo = workspace.root / "vendor" / expected["directory"]
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        runtime, "git", lambda path, *args: expected["commit"] if "rev-parse" in args else ""
    )
    assert runtime.evaluator(workspace, "omnidocbench") == (repo, expected)
