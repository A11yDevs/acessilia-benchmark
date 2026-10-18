"""Exercise orchestration failures without calling providers."""

from pathlib import Path

import pytest

from acessilia_benchmark.core.runs import prepare, validate_predictions
from acessilia_benchmark.io import read
from acessilia_benchmark.processes import ProcessResult
from acessilia_benchmark.services import inference


@pytest.mark.parametrize("status", ["ok", "failed", "timeout"])
def test_inference_records_evidence_and_blocks_partial_results(
    workspace, dataset_factory, monkeypatch, tmp_path, status
):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
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
        target = destination / "predictions" / plan["cases"][0]["prediction"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")
        return ProcessResult(0 if status == "ok" else 1, 1.5, status == "timeout")

    monkeypatch.setattr(inference, "run_logged", run)
    if status == "ok":
        inference.predict(workspace, "round", tmp_path, None)
        validate_predictions(destination, plan)
        evidence = destination / "system.json"
        evidence.write_text("changed", encoding="utf-8")
        with pytest.raises(ValueError, match="Evidência"):
            validate_predictions(destination, plan)
    else:
        with pytest.raises(ValueError, match="incompleta"):
            inference.predict(workspace, "round", tmp_path, None)
        assert not (destination / "prediction-manifest.json").exists()
        assert not list((destination / "predictions").rglob("*.md"))
    assert read(destination / "inference.json")["status"] == ("ok" if status == "ok" else "failed")
