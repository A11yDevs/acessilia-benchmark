"""Exercise orchestration failures without calling providers."""

from pathlib import Path

import pytest

from acessilia_benchmark.core.runs import prepare, validate_predictions
from acessilia_benchmark.io import read
from acessilia_benchmark.processes import ProcessResult
from acessilia_benchmark.services import inference
from acessilia_benchmark.services.toolbox import ToolboxSettings


def _mock_toolbox(monkeypatch, *, ok=True):
    settings = ToolboxSettings(
        endpoints=("http://toolbox.test",),
        providers=("docling",),
        ai_client="ollama",
        api_key="private-key",
    )
    monkeypatch.setattr(inference, "read_toolbox_settings", lambda *_: settings)
    monkeypatch.setattr(
        inference,
        "check_toolbox",
        lambda *_: {
            "ok": ok,
            "providers": {"docling": {"ok": ok}},
            "identity": {
                "services": [{"endpoint": "http://toolbox.test", "git_commit": "toolbox"}],
                "providers": [{"provider": "docling", "endpoints": []}],
            },
        },
    )


@pytest.mark.parametrize("status", ["ok", "failed", "timeout"])
def test_inference_records_evidence_and_blocks_partial_results(
    workspace, dataset_factory, monkeypatch, tmp_path, status
):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
    _mock_toolbox(monkeypatch)
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    monkeypatch.setattr(inference, "git", lambda *args: "commit" if "rev-parse" in args else "")

    def run(command, log, *, timeout, env):
        assert command[1].endswith("/acessilia_benchmark/adapters/acessilia.py")
        assert Path(command[1]).is_file()
        assert env["PDDL_EXECUTE_DRY_RUN"] == "false"
        assert env["DATA_DIR"].startswith(str(destination))
        assert "reference" not in read(
            destination / "requests" / (plan["cases"][0]["prediction"] + ".json")
        )
        if status == "failed":
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(
                "ToolboxTimeout: provider deadline reached; authorization=private-secret",
                encoding="utf-8",
            )
        target = destination / "predictions" / plan["cases"][0]["prediction"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")
        return ProcessResult(0 if status == "ok" else 1, 1.5, status == "timeout")

    monkeypatch.setattr(inference, "run_logged", run)
    if status == "ok":
        inference.predict(workspace, "round", tmp_path, None)
        validate_predictions(destination, plan)
        system = read(destination / "system.json")
        assert system["toolbox_runtime"]["services"][0]["git_commit"] == "toolbox"
        assert "private-key" not in str(system)
        evidence = destination / "system.json"
        evidence.write_text("changed", encoding="utf-8")
        with pytest.raises(ValueError, match="Evidência"):
            validate_predictions(destination, plan)
    else:
        with pytest.raises(ValueError, match="incompleta"):
            inference.predict(workspace, "round", tmp_path, None)
        assert not (destination / "prediction-manifest.json").exists()
        assert not list((destination / "predictions").rglob("*.md"))
        row = read(destination / "inference.json")["cases"][0]
        expected_kind = "benchmark_timeout" if status == "timeout" else "provider_timeout"
        assert row["failure_kind"] == expected_kind
        assert row["failure_kinds"] == {expected_kind: 1}
        report = (destination / "runtime-report/report.md").read_text()
        assert expected_kind in report
        assert "private-secret" not in report
    assert read(destination / "inference.json")["status"] == ("ok" if status == "ok" else "failed")


@pytest.mark.parametrize(
    "error,kind",
    [
        ("ToolboxTimeout: gateway deadline", "provider_timeout"),
        (
            "acessilia_sdk.toolbox.errors.ToolboxProviderUnavailable: HTTP 503",
            "provider_unavailable",
        ),
    ],
)
def test_resume_preserves_provider_failures_after_eventual_success(
    workspace, dataset_factory, monkeypatch, tmp_path, error, kind
):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "retry", workspace.data, 1, 42)
    _mock_toolbox(monkeypatch)
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    monkeypatch.setattr(inference, "git", lambda *args: "commit" if "rev-parse" in args else "")
    calls = iter((error, None))

    def run(command, log, *, timeout, env):
        error = next(calls)
        if error:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(error, encoding="utf-8")
            return ProcessResult(1, 2.0, False)
        target = destination / "predictions" / plan["cases"][0]["prediction"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")
        return ProcessResult(0, 1.0, False)

    monkeypatch.setattr(inference, "run_logged", run)
    with pytest.raises(ValueError, match="incompleta"):
        inference.predict(workspace, "retry", tmp_path, None)
    inference.predict(workspace, "retry", tmp_path, None, resume=True)

    row = read(destination / "inference.json")["cases"][0]
    assert row["status"] == "ok"
    assert row["failure_kind"] is None
    assert row["failure_kinds"] == {kind: 1}
    assert read(destination / "runtime-report/summary.json")["runtime"]["failures_by_kind"] == {
        "benchmark_timeout": 0,
        "provider_timeout": int(kind == "provider_timeout"),
        "provider_unavailable": int(kind == "provider_unavailable"),
        "process_failed": 0,
    }


def test_structure_engine_requires_explicit_provider(
    workspace, dataset_factory, monkeypatch, tmp_path
):
    dataset_factory()
    prepare(workspace, "omnidocbench", "structure", workspace.data, 1, 42)
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    with pytest.raises(ValueError, match="requer --provider"):
        inference.predict(workspace, "structure", tmp_path, None, engine="structure")


def test_inference_stops_before_writing_when_toolbox_provider_is_unhealthy(
    workspace, dataset_factory, monkeypatch, tmp_path
):
    dataset_factory()
    destination, _ = prepare(workspace, "omnidocbench", "blocked", workspace.data, 1, 42)
    _mock_toolbox(monkeypatch, ok=False)
    monkeypatch.setattr(inference, "resolve_python", lambda *args: (tmp_path / "python", {}))
    with pytest.raises(ValueError, match="Pré-verificação Toolbox falhou"):
        inference.predict(workspace, "blocked", tmp_path, None)
    assert not (destination / "system.json").exists()
    assert not (destination / "inference.json").exists()
