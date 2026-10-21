"""Sealed inference recovery and provider baseline contracts."""

import sys
from pathlib import Path

import pytest

from acessilia_benchmark.core.runs import prepare, validate_predictions
from acessilia_benchmark.io import read, write
from acessilia_benchmark.processes import ProcessResult
from acessilia_benchmark.services import inference


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
