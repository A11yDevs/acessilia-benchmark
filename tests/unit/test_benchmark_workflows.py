"""Sealed regression comparisons and inference recovery contracts."""

import sys
from pathlib import Path

import pytest

from acessilia_benchmark.core.runs import import_predictions, prepare, validate_predictions
from acessilia_benchmark.io import digest, read, seal, write
from acessilia_benchmark.processes import ProcessResult
from acessilia_benchmark.services import comparison, inference


def imported(workspace, name, dataset="omnidocbench", limit=0, window_size=1):
    destination, plan = prepare(
        workspace, dataset, name, workspace.data, limit, 42, window_size=window_size
    )
    source = workspace.root / f"source-{name}"
    for case in plan["cases"]:
        path = source / case["prediction"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"generated {case['id']}", encoding="utf-8")
    import_predictions(workspace, name, source, name)
    return destination, plan


def evaluated(workspace, name, *, limit=0, distance=0.1, teds=0.9):
    destination, plan = imported(workspace, name, limit=limit)
    artifacts = destination / "basic"
    write(
        artifacts / "summary.json",
        {
            "profile": "basic",
            "overall": None,
            "overall_details": {"protocol": None},
            "coverage": {"cases": len(plan["cases"])},
            "metrics": {
                "text_block": {"Edit_dist": {"ALL": distance}},
                "table": {"TEDS": {"ALL": teds}},
            },
        },
    )
    seal(artifacts / "summary.json")
    write(
        artifacts / "execution.json",
        {
            "status": "ok",
            "predictions_sha256": validate_predictions(destination, plan),
            "artifacts_sha256": {"summary.json": digest(artifacts / "summary.json")},
        },
    )
    seal(artifacts / "execution.json")
    return artifacts


def test_comparison_detects_direction_and_percentage_point_tolerance(workspace, dataset_factory):
    dataset_factory()
    evaluated(workspace, "base")
    evaluated(workspace, "candidate", distance=0.05, teds=0.88)
    result = comparison.compare(workspace, "base", "candidate", "basic")
    assert result["quality_regressions"] == ["table/TEDS/ALL"]
    assert result["metrics"]["text_block/Edit_dist/ALL"]["gain_points"] == pytest.approx(5)
    assert (
        comparison.compare(workspace, "base", "candidate", "basic", 2.01)["verdict"]
        == "no_regression"
    )


@pytest.mark.parametrize("change", ["selection", "tamper", "missing_metric"])
def test_comparison_refuses_incompatible_or_modified_results(workspace, dataset_factory, change):
    dataset_factory()
    evaluated(workspace, "base")
    artifacts = evaluated(
        workspace,
        "candidate",
        limit=1 if change == "selection" else 0,
        teds=None if change == "missing_metric" else 0.9,
    )
    if change == "tamper":
        (artifacts / "summary.json").write_text("{}")
    with pytest.raises(ValueError):
        comparison.compare(workspace, "base", "candidate", "basic")


def test_comparison_cli_returns_failure_for_regression(workspace, dataset_factory, monkeypatch):
    from acessilia_benchmark import cli

    dataset_factory()
    evaluated(workspace, "base")
    evaluated(workspace, "candidate", distance=0.5)
    monkeypatch.setattr(cli.Workspace, "discover", lambda: workspace)
    monkeypatch.setattr(
        sys,
        "argv",
        ["bench", "compare", "base", "candidate", "--profile", "basic", "--fail-on-regression"],
    )
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1


@pytest.fixture
def partial(workspace, dataset_factory, monkeypatch):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "recover", workspace.data, 2, 42)
    monkeypatch.setattr(inference, "resolve_python", lambda *a: (Path(sys.executable), {}))
    monkeypatch.setattr(inference, "git", lambda *a: "commit" if "rev-parse" in a else "")
    calls = []

    def generate(command, log, **kwargs):
        output = Path(command[command.index("--output") + 1])
        calls.append(output.name)
        if len(calls) == 2:
            return ProcessResult(1, 3, False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("generated", encoding="utf-8")
        return ProcessResult(0, 2, False)

    monkeypatch.setattr(inference, "run_logged", generate)
    with pytest.raises(ValueError, match="incompleta"):
        inference.predict(workspace, "recover", workspace.root, None)
    return destination, plan, calls


def test_resume_retries_only_failed_cases_and_accounts_for_all_time(workspace, partial):
    destination, plan, calls = partial
    inference.predict(workspace, "recover", workspace.root, None, resume=True)
    assert len(calls) == 3

    assert calls[1] == calls[2]
    validate_predictions(destination, plan)
    assert (destination / "attempts/1/inference.json").is_file()
    report = read(destination / "runtime-report/summary.json")
    assert report["runtime"]["total_seconds"] == 7
    inference.predict(workspace, "recover", workspace.root, None, resume=True)
    assert len(calls) == 3


def test_runtime_comparison_accepts_partial_runs_without_claiming_quality(workspace, partial):
    result = comparison.compare(workspace, "recover", "recover", "runtime")
    assert result["verdict"] == "runtime_only"
    assert result["metrics"] == {}
    assert result["runtime"]["base"]["failures"] == 1
    assert result["runtime_deltas"]["total_seconds"] == 0


@pytest.mark.parametrize("change", ["prediction", "core", "system", "metadata"])
def test_resume_refuses_changed_successes_or_system(workspace, partial, change, monkeypatch):
    destination, plan, calls = partial
    if change == "core":
        monkeypatch.setattr(inference, "git", lambda *a: "new-commit")
    elif change == "system":
        write(destination / "system.json", {})
    else:
        first = destination / "predictions" / plan["cases"][0]["prediction"]
        (first if change == "prediction" else first.with_suffix(".metadata.json")).write_text(
            "changed"
        )
    with pytest.raises(ValueError):
        inference.predict(workspace, "recover", workspace.root, None, resume=True)
    assert len(calls) == 2


def test_structure_rejects_two_page_input_before_provider_calls(workspace, dataset_factory):
    dataset_factory("drdocbench-dev")
    prepare(workspace, "drdocbench-dev", "two", workspace.data, 1, 42)
    with pytest.raises(ValueError, match="uma página"):
        inference.predict(
            workspace, "two", workspace.root, None, engine="structure", provider="docling"
        )
