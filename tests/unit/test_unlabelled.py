"""Unlabelled test split preserves input-only inference and reports failures."""

import json
from pathlib import Path

import pytest

from acessilia_benchmark.core.runs import load_plan, prepare
from acessilia_benchmark.core.sampling import ordered_cases
from acessilia_benchmark.io import read
from acessilia_benchmark.processes import ProcessResult
from acessilia_benchmark.services import inference
from acessilia_benchmark.services.evaluation import evaluate


def test_unlabelled_windows_require_no_references(workspace, dataset_factory):
    dataset_factory("drdocbench-test")
    cases = list(ordered_cases(workspace, "drdocbench-test", workspace.data, 42))
    assert len(cases) == 3
    assert all(not case["references"] and not case["reference_markdown"] for case in cases)
    assert sorted(case["prediction"] for case in cases) == [
        "DOMAIN/document_page_10-11.md",
        "DOMAIN/document_page_2-3.md",
        "DOMAIN/document_page_9-10.md",
    ]
    destination, plan = prepare(workspace, "drdocbench-test", "test", workspace.data, 0, 42)
    assert plan["reference_sha256"] == {}
    assert plan["unique_pages"] == 5
    assert plan["evaluator"] is None
    load_plan(workspace, "test")
    for request in (destination / "requests").rglob("*.json"):
        assert set(read(request)) == {"id", "images"}
    for profile in ("basic", "full"):
        with pytest.raises(ValueError, match="sem referências"):
            evaluate(workspace, "test", profile)
    with pytest.raises(ValueError, match="smoke indisponível"):
        prepare(workspace, "drdocbench-test", "smoke", workspace.data, 10, 42, fixture=True)
    assert not workspace.run_dir("smoke").exists()


@pytest.mark.parametrize("failure", [False, True])
def test_runtime_report_includes_unsuccessful_attempts(
    workspace, dataset_factory, monkeypatch, tmp_path, failure
):
    dataset_factory("drdocbench-test")
    destination, plan = prepare(workspace, "drdocbench-test", "test", workspace.data, 0, 42)
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    monkeypatch.setattr(inference, "git", lambda *args: "commit")
    statuses = iter(["ok", "timeout", "failed"] if failure else ["ok"] * 3)

    def run(command, log, **kwargs):
        status = next(statuses)
        target = command[command.index("--output") + 1]
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated")
        return ProcessResult(0 if status == "ok" else 1, 2.0, status == "timeout")

    monkeypatch.setattr(inference, "run_logged", run)
    if failure:
        with pytest.raises(ValueError, match="incompleta"):
            inference.predict(workspace, "test", tmp_path, None)
        assert not (destination / "prediction-manifest.json").exists()
    else:
        inference.predict(workspace, "test", tmp_path, None)
    evaluate(workspace, "test")
    summary = read(destination / "runtime-report/summary.json")
    assert summary["overall"] is None
    assert summary["quality_metrics"] is None
    assert summary["coverage"]["attempted_cases"] == 3
    runtime = summary["runtime"]
    assert runtime["total_seconds"] == 6
    assert runtime["p95_seconds_per_window"] == 2
    assert runtime["successful_pages_per_minute"] == (20 if failure else 60)
    assert runtime["failures"] == (2 if failure else 0)
    assert runtime["timeouts"] == int(failure)
    rows = [json.loads(line) for line in (destination / "timings.jsonl").read_text().splitlines()]
    rows[0]["seconds"] = 999
    (destination / "timings.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="divergentes"):
        evaluate(workspace, "test", "runtime")
