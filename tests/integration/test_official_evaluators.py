"""Explicit integration suite: requires downloaded data and `acessilia-benchmark setup`."""

import uuid
from pathlib import Path

import pytest

from acessilia_benchmark.core.workspace import Workspace
from acessilia_benchmark.io import read
from acessilia_benchmark.services.selfcheck import smoke


@pytest.mark.integration
@pytest.mark.parametrize("dataset", ["drdocbench-dev", "omnidocbench"])
def test_official_evaluator_with_real_dataset(dataset):
    workspace = Workspace(Path(__file__).resolve().parents[2])
    name = f"integration-{dataset}-{uuid.uuid4().hex[:8]}"
    smoke(workspace, dataset, name, workspace.data)
    artifacts = workspace.run_dir(name) / "basic"
    assert read(artifacts / "execution.json")["status"] == "ok"
    summary = read(artifacts / "summary.json")
    assert summary["fixture"] is True
    assert summary["overall"] is None
    assert summary["coverage"]["cases"] == 10
    assert summary["coverage"]["scored_cases"] == 10
    assert all(
        summary["metrics"][component]
        for component in ("text_block", "table", "display_formula", "reading_order")
    )


@pytest.mark.integration
@pytest.mark.parametrize("dataset", ["drdocbench-dev", "omnidocbench"])
def test_full_metrics_and_overall_against_official_artifacts(dataset, request):
    import json
    import os
    from statistics import mean

    from acessilia_benchmark.services.evaluation import evaluate

    if not request.config.getoption("--run-full") and os.environ.get("ACESSILIA_TEST_FULL") != "1":
        pytest.skip("Opt-in: execute pytest tests/integration --run-full")
    workspace = Workspace(Path(__file__).resolve().parents[2])
    name = f"integration-full-{dataset}-{uuid.uuid4().hex[:8]}"
    smoke(workspace, dataset, name, workspace.data)
    evaluate(workspace, name, "full", timeout=600)
    artifacts = workspace.run_dir(name) / "full"
    summary = read(artifacts / "summary.json")
    assert read(artifacts / "execution.json")["status"] == "ok"
    assert summary["fixture"] and summary["overall"] is not None
    assert summary["coverage"]["scored_cases"] == 10
    assert summary["metrics"]["display_formula"]["CDM"]["all"] == pytest.approx(1)
    assert not summary["overall_details"]["leaderboard_comparable"]
    result = artifacts / "result"
    if dataset == "omnidocbench":
        # The pinned evaluator independently mirrors its official notebook.
        official = read(next(result.glob("*_run_summary.json")))
        expected = official["notebook_metric_summary"]["overall_notebook"]
        assert summary["overall"] == pytest.approx(expected)
    else:
        # Independent aggregation of evaluator per-window JSON and block metrics.
        components = {}
        for component in ("text_block", "reading_order"):
            for image, distance in read(
                next(result.glob(f"*_{component}_per_page_edit.json"))
            ).items():
                components.setdefault(image, []).append((1 - distance) * 100)
        for component, metric in (("table", "TEDS"), ("display_formula", "CDM")):
            values = {}
            for row in read(next(result.glob(f"*_{component}_result.json"))):
                values.setdefault(row["img_id"], []).append(row["metric"][metric])
            for image, scores in values.items():
                components.setdefault(image, []).append(mean(scores) * 100)
        expected = mean(mean(scores) for scores in components.values())
        assert summary["overall"] == pytest.approx(expected)
    assert "Overall local" in (artifacts / "report.md").read_text()
    print(json.dumps({"run": name, "overall": summary["overall"], "expected": expected}))
