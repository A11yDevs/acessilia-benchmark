from pathlib import Path

import pytest

from acessilia_benchmark.core.catalog import verify
from acessilia_benchmark.core.runs import (
    import_predictions,
    load_plan,
    prediction_hashes,
    prepare,
    validate_predictions,
)
from acessilia_benchmark.core.sampling import ordered_cases
from acessilia_benchmark.io import local_path, read, write


def test_dataset_integrity_and_equal_length_corruption(workspace, dataset_factory):
    snapshot, spec = dataset_factory()
    verify("omnidocbench", spec, workspace.data)
    path = snapshot / "images/page-0.png"
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(ValueError, match="corrompido"):
        verify("omnidocbench", spec, workspace.data)


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "..", "bad/name", "bad name"])
def test_run_names_are_confined(workspace, name):
    with pytest.raises(ValueError):
        workspace.run_dir(name)


def test_symlinks_cannot_escape_artifact_directory(tmp_path):
    folder = tmp_path / "artifacts"
    folder.mkdir()
    (folder / "outside").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="fora"):
        local_path(folder, "outside/file.md")


def test_numeric_windows_do_not_cross_gaps(workspace, dataset_factory):
    dataset_factory("drdocbench-dev")
    first = list(ordered_cases(workspace, "drdocbench-dev", workspace.data, 42))
    assert first == list(ordered_cases(workspace, "drdocbench-dev", workspace.data, 42))
    assert {case["id"] for case in first} == {
        "DOMAIN/document_page_2-3",
        "DOMAIN/document_page_9-10",
        "DOMAIN/document_page_10-11",
    }
    assert first != list(ordered_cases(workspace, "drdocbench-dev", workspace.data, 99))


def test_requests_contain_images_only(workspace, dataset_factory):
    dataset_factory()
    destination, plan = prepare(
        workspace, "omnidocbench", "round", workspace.data, 10, 42, fixture=True
    )
    assert plan["fixture"] is True
    assert len(plan["cases"]) == 3
    for path in (destination / "requests").rglob("*.json"):
        assert set(read(path)) == {"id", "images"}
    load_plan(workspace, "round")


def test_plan_flag_tampering_is_rejected(workspace, dataset_factory):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
    plan["fixture"] = True
    write(destination / "plan.json", plan)
    with pytest.raises(ValueError, match="integridade"):
        load_plan(workspace, "round")


@pytest.mark.parametrize("target", ["input", "reference", "lock"])
def test_modified_dependencies_or_data_are_rejected(workspace, dataset_factory, target):
    dataset_factory()
    _, plan = prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
    path = (
        Path(next(iter(plan["input_sha256"])))
        if target == "input"
        else Path(next(iter(plan["reference_sha256"])))
        if target == "reference"
        else workspace.root / "evaluation/uv.lock"
    )
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(workspace, "round")


def test_missing_extra_and_empty_outputs_are_distinguished(tmp_path):
    plan = {"cases": [{"prediction": "subject/case.md"}]}
    with pytest.raises(ValueError, match="1 ausentes"):
        prediction_hashes(tmp_path, plan)
    (tmp_path / "subject").mkdir()
    (tmp_path / "subject/case.md").write_text("", encoding="utf-8")
    assert len(prediction_hashes(tmp_path, plan)) == 1
    (tmp_path / "extra.md").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="1 extras"):
        prediction_hashes(tmp_path, plan)


def test_import_is_sealed_and_does_not_claim_acessilia(workspace, dataset_factory, tmp_path):
    dataset_factory()
    destination, plan = prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
    source = tmp_path / "external"
    source.mkdir()
    filename = plan["cases"][0]["prediction"]
    (source / filename).write_text("prediction", encoding="utf-8")
    import_predictions(workspace, "round", source, "external-model")
    validate_predictions(destination, plan)
    assert read(destination / "prediction-manifest.json")["origin"] == {
        "kind": "imported",
        "label": "external-model",
    }
    (destination / "predictions" / filename).write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="alteradas"):
        validate_predictions(destination, plan)


def test_evaluator_changes_in_catalog_invalidate_existing_plan(workspace, dataset_factory):
    dataset_factory()
    prepare(workspace, "omnidocbench", "round", workspace.data, 1, 42)
    catalog_path = workspace.root / "datasets/registry.json"
    catalog = read(catalog_path)
    catalog["datasets"]["omnidocbench"]["evaluator"]["commit"] = "changed"
    write(catalog_path, catalog)
    with pytest.raises(ValueError, match="configuração do avaliador mudou"):
        load_plan(workspace, "round")
