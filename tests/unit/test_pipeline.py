"""Orchestration contracts, without provider calls or downloads."""

from pathlib import Path

import pytest

from acessilia_benchmark.services import pipeline


@pytest.fixture
def steps(monkeypatch, dataset_factory):
    dataset_factory()
    calls = []
    for operation in (
        "download",
        "setup",
        "install_render_tools",
        "runtime_versions",
        "prepare",
        "predict",
        "evaluate",
    ):
        monkeypatch.setattr(
            pipeline,
            operation,
            lambda *args, _op=operation, **kwargs: calls.append((_op, args, kwargs)),
        )
    monkeypatch.setattr(pipeline, "resolve_python", lambda *args: (Path("/core/python"), {}))
    return calls


def test_default_pipeline_is_full_dataset_with_full_metrics(workspace, steps):
    report = pipeline.run_dataset(
        workspace,
        "omnidocbench",
        Path("/core"),
        name="trial",
        timeout=123,
        evaluation_timeout=456,
    )
    assert [s[0] for s in steps] == [
        "setup",
        "install_render_tools",
        "runtime_versions",
        "prepare",
        "predict",
        "evaluate",
    ]
    prepared = next(step for step in steps if step[0] == "prepare")
    assert prepared[1][4] == 0
    assert steps[-1][1][2] == "full"
    assert steps[-2][1][-1] == 123
    assert steps[-1][2]["timeout"] == 456
    assert report == workspace.root / "runs/trial/full/report.md"


def test_download_only_when_manifest_missing(workspace, steps):
    next(workspace.data.rglob("download-manifest.json")).unlink()
    pipeline.run_dataset(workspace, "omnidocbench", Path("/core"))
    assert steps[0][0] == "download"


def test_offline_never_downloads_or_sets_up(workspace, steps):
    pipeline.run_dataset(workspace, "omnidocbench", Path("/core"), offline=True, skip_setup=True)
    assert not {"download", "setup"} & {s[0] for s in steps}


def test_existing_run_stops_before_side_effects(workspace, steps):
    workspace.run_dir("old").mkdir(parents=True)
    with pytest.raises(ValueError, match="já existe"):
        pipeline.run_dataset(workspace, "omnidocbench", Path("/core"), name="old")
    assert not steps


@pytest.mark.parametrize(
    "kwargs", [{"limit": -1}, {"timeout": 0}, {"evaluation_timeout": 0}, {"offline": True}]
)
def test_invalid_options_stop_before_side_effects(workspace, steps, kwargs):
    with pytest.raises(ValueError):
        pipeline.run_dataset(workspace, "omnidocbench", Path("/core"), **kwargs)
    assert not steps


def test_unlabelled_auto_uses_runtime(workspace, steps, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "load_registry",
        lambda _: {
            "test": {"evaluator": None, "revision": "fixture"},
        },
    )
    report = pipeline.run_dataset(workspace, "test", Path("/core"), skip_setup=True)
    assert steps[-1][1][2] == "runtime"
    assert report.parent.name == "runtime-report"
    assert "runtime_versions" not in [s[0] for s in steps]
    steps.clear()
    with pytest.raises(ValueError, match="sem referências"):
        pipeline.run_dataset(workspace, "test", Path("/core"), profile="full")
    assert not steps


def test_failed_inference_never_scores(workspace, steps, monkeypatch):
    def failed(*args):
        raise ValueError("Inferência incompleta")

    monkeypatch.setattr(pipeline, "predict", failed)
    with pytest.raises(ValueError, match="incompleta"):
        pipeline.run_dataset(workspace, "omnidocbench", Path("/core"))
    assert "evaluate" not in [s[0] for s in steps]


def test_real_orchestration_generates_sealed_runtime_report(
    workspace, dataset_factory, monkeypatch, tmp_path
):
    from acessilia_benchmark.core.runs import load_plan, validate_predictions
    from acessilia_benchmark.io import read
    from acessilia_benchmark.processes import ProcessResult
    from acessilia_benchmark.services import inference

    dataset_factory()
    monkeypatch.setattr(pipeline, "resolve_python", lambda *args: (tmp_path / "python", {}))
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    monkeypatch.setattr(inference, "git", lambda *args: "commit" if "rev-parse" in args else "")

    def generate(command, log, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("Generated Markdown", encoding="utf-8")
        return ProcessResult(0, 1.5, False)

    monkeypatch.setattr(inference, "run_logged", generate)
    report = pipeline.run_dataset(
        workspace,
        "omnidocbench",
        tmp_path,
        name="combined",
        profile="runtime",
        skip_setup=True,
        offline=True,
    )
    assert report.is_file()
    destination, plan = load_plan(workspace, "combined")
    assert len(plan["cases"]) == 3
    validate_predictions(destination, plan)
    assert read(destination / "inference.json")["status"] == "ok"
    assert "Generated Markdown" in next((destination / "predictions").glob("*.md")).read_text()


@pytest.mark.parametrize("action", ["run", "prepare", "evaluate"])
def test_cli_defaults_use_complete_dataset_and_auto_profile(
    workspace, dataset_factory, monkeypatch, action
):
    import sys

    from acessilia_benchmark import cli

    dataset_factory()
    monkeypatch.setattr(cli.Workspace, "discover", lambda: workspace)
    calls = []
    monkeypatch.setattr(cli, "run_dataset", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(cli, "prepare", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(cli, "evaluate", lambda *a, **kw: calls.append((a, kw)))
    arguments = ["acessilia-benchmark", action]
    if action != "evaluate":
        arguments.append("omnidocbench")
    arguments += ["--run", "default-check"]
    if action == "run":
        arguments += ["--acessilia-repo", "/core"]
    monkeypatch.setattr(sys, "argv", arguments)
    cli.main()
    args, kwargs = calls[0]
    if action == "run":
        assert kwargs["limit"] == 0
        assert kwargs["profile"] == "auto"
    elif action == "prepare":
        assert args[4] == 0
    else:
        assert args[2] == "auto"
