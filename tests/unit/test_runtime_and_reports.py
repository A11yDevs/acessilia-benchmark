import sys
import time
from pathlib import Path

import fitz
import pytest
from PIL import Image

from acessilia_benchmark.adapters.acessilia import pack_images
from acessilia_benchmark.core.scoring import compute_overall
from acessilia_benchmark.io import read, write
from acessilia_benchmark.processes import run_logged
from acessilia_benchmark.reporting import (
    _failure_counts,
    normalize_numbers,
    processing_assessment,
    summarize,
)
from acessilia_benchmark.services.doctor import interpreter_info, resolve_python
from acessilia_benchmark.services.evaluation import (
    config_for,
    evaluate,
    validate_cdm,
    validate_metrics,
)


def test_virtual_environment_symlink_is_not_resolved(tmp_path, monkeypatch):
    candidate = tmp_path / ".venv/bin/python"
    candidate.parent.mkdir(parents=True)
    candidate.symlink_to(sys.executable)
    monkeypatch.setattr(
        "acessilia_benchmark.services.doctor.interpreter_info",
        lambda *_: {
            "modules": {
                name: True
                for name in ("agno", "fitz", "PIL", "fastapi", "docstruct", "acessilia_sdk")
            }
        },
    )
    selected, _ = resolve_python(tmp_path, candidate)
    assert selected == candidate
    assert selected != candidate.resolve()


def test_interpreter_probe_keeps_real_venv_prefix(tmp_path):
    info = interpreter_info(Path(sys.executable), tmp_path)
    assert info["prefix"] == sys.prefix


def test_empty_core_environment_has_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="Informe --python"):
        resolve_python(tmp_path, tmp_path / "missing/bin/python")


def test_timeout_stops_descendant_process(tmp_path):
    pid_file = tmp_path / "child.pid"
    child = "import time; time.sleep(30)"
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    result = run_logged([sys.executable, "-c", parent], tmp_path / "process.log", timeout=0.5)
    assert result.timed_out
    assert result.seconds < 5
    pid = int(pid_file.read_text())
    status = Path(f"/proc/{pid}/stat")
    for _ in range(20):
        try:
            if status.read_text().split()[2] == "Z":
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(0.02)
    else:
        pytest.fail("Descendant remained running after timeout")


def test_pdf_embeds_original_jpeg_streams_without_recompression(tmp_path):
    images = [tmp_path / "first.jpg", tmp_path / "second.jpg"]
    for path, color in zip(images, ("red", "blue"), strict=True):
        with Image.new("RGB", (30, 40), color) as image:
            image.save(path, quality=92)
    target = tmp_path / "window.pdf"
    pack_images(images, target)
    with fitz.open(target) as document:
        assert len(document) == 2
        for page, original in zip(document, images, strict=True):
            xref = page.get_images()[0][0]
            assert document.extract_image(xref)["image"] == original.read_bytes()


def test_basic_and_full_metrics_are_explicit():
    plan = {"dataset": "omnidocbench"}
    basic = config_for(Path("/tmp/round"), plan, "basic")
    full = config_for(Path("/tmp/round"), plan, "full")
    assert basic["end2end_eval"]["metrics"]["display_formula"]["metric"] == ["Edit_dist"]
    assert full["end2end_eval"]["metrics"]["display_formula"]["metric"] == ["Edit_dist", "CDM"]


def test_missing_official_component_is_not_success(tmp_path):
    with pytest.raises(ValueError, match="incompletas"):
        validate_metrics(tmp_path, {})


def test_non_finite_metrics_are_null_not_zero():
    assert normalize_numbers({"a": float("nan"), "b": "NaN", "c": [float("inf"), 0.0]}) == {
        "a": None,
        "b": None,
        "c": [None, 0.0],
    }


def test_processing_diagnostics_are_reported_without_assuming_success(tmp_path):
    plan = {"cases": [{"id": "a", "prediction": "a.md"}, {"id": "b", "prediction": "b.md"}]}
    write(
        tmp_path / "predictions/a.metadata.json",
        {
            "technical_warnings": [],
            "processing_diagnostics": {
                "pddl_visual_failures": {"pictures": {"provider": 1}},
                "pddl_extraction_degraded": True,
                "pddl_extraction_failures": {"mineru": "TimeoutError"},
            },
        },
    )
    write(tmp_path / "predictions/b.metadata.json", {"technical_warnings": None})
    result = processing_assessment(tmp_path, plan, "acessilia")
    assert result["status"] == "unknown"
    assert result["cases"][0]["status"] == "reported_warnings"
    assert result["cases"][0]["signals"] == [
        "visual_failures",
        "extraction_degraded",
    ]
    assert result["cases"][1]["status"] == "unknown"
    assert processing_assessment(tmp_path, plan, "imported")["status"] == "not_available"


def test_formula_pages_require_core_formula_diagnostics_to_claim_clean_processing(tmp_path):
    plan = {
        "fixture": False,
        "cases": [
            {
                "id": "document-page-9-10",
                "prediction": "document_page_9-10.md",
                "images": ["/fixtures/page_9.jpg", "/fixtures/page_10.jpg"],
            }
        ],
        "unique_pages": 1,
        "dataset": "omnidocbench",
        "dataset_revision": "revision",
        "evaluator": {"commit": "commit"},
    }
    write(tmp_path / "prediction-manifest.json", {"origin": {"kind": "acessilia"}})
    write(
        tmp_path / "predictions/document_page_9-10.metadata.json",
        {
            "technical_warnings": [],
            "processing_diagnostics": {"pddl_formula_diagnostics": None},
        },
    )
    write(
        tmp_path / "result/sample_display_formula_result.json",
        [{"img_id": "book_document_page_9.png", "gt": "x^2", "pred": "x^2"}],
    )
    summarize(tmp_path, plan, tmp_path, {}, "basic")
    processing = read(tmp_path / "summary.json")["processing"]
    assert processing["status"] == "unknown"
    assert processing["cases"][0]["status"] == "unknown"
    assert processing["cases"][0]["signals"] == ["formula_diagnostics_unavailable"]


def test_missing_formula_diagnostics_remain_unknown_even_with_warnings(tmp_path):
    plan = {
        "cases": [
            {
                "id": "page-9",
                "prediction": "page_9.md",
                "images": ["/fixtures/page_9.jpg"],
            },
            {"id": "page-10", "prediction": "page_10.md", "images": ["/fixtures/page_10.jpg"]},
        ],
    }
    write(
        tmp_path / "predictions/page_9.metadata.json",
        {
            "technical_warnings": ["falha visual reportada"],
            "processing_diagnostics": {"pddl_formula_diagnostics": None},
        },
    )
    write(
        tmp_path / "predictions/page_10.metadata.json",
        {"technical_warnings": ["aviso reportado"], "processing_diagnostics": {}},
    )
    result = processing_assessment(tmp_path, plan, "acessilia", formula_page_stems={"page_9"})
    assert result["cases"][0]["status"] == "unknown"
    assert result["cases"][1]["status"] == "reported_warnings"
    assert result["status"] == "unknown"


def test_runtime_failure_categories_count_all_attempts_and_read_legacy_rows():
    assert _failure_counts(
        [
            {
                "status": "ok",
                "failure_kinds": {"provider_timeout": 1, "provider_unavailable": 2},
            },
            {"status": "timeout"},
            {"status": "failed"},
        ]
    ) == {
        "benchmark_timeout": 1,
        "provider_timeout": 1,
        "provider_unavailable": 2,
        "process_failed": 1,
    }


def test_formula_fallbacks_and_provider_limits_are_review_signals(tmp_path):
    plan = {
        "cases": [{"id": "a", "prediction": "a.md", "images": ["/fixtures/a.jpg"]}],
    }
    write(
        tmp_path / "predictions/a.metadata.json",
        {
            "technical_warnings": [],
            "processing_diagnostics": {
                "pddl_formula_diagnostics": {
                    "attempted": 2,
                    "recognized": 1,
                    "vision_fallbacks": 1,
                    "unrecognized": 1,
                },
                "pddl_external_provider_limits": {"vision": 1},
            },
        },
    )
    result = processing_assessment(tmp_path, plan, "acessilia")
    assert result["status"] == "reported_warnings"
    assert result["cases"][0]["signals"] == [
        "formula_vision_fallback",
        "formulas_unrecognized",
        "external_provider_limits",
    ]


def test_quality_report_shows_warnings_and_their_limit(tmp_path):
    plan = {
        "fixture": False,
        "cases": [{"id": "a", "prediction": "a.md"}],
        "unique_pages": 1,
        "dataset": "test",
        "dataset_revision": "r",
        "evaluator": {"commit": "c"},
    }
    write(tmp_path / "prediction-manifest.json", {"origin": {"kind": "acessilia"}})
    write(tmp_path / "predictions/a.metadata.json", {"technical_warnings": ["falha visual"]})
    summarize(tmp_path, plan, tmp_path, {}, "basic")
    assert read(tmp_path / "summary.json")["processing"]["status"] == "reported_warnings"
    report = (tmp_path / "report.md").read_text()
    assert "falha visual" in report
    assert "não comprova processamento completo" in report


def test_fixture_report_never_claims_system_performance(tmp_path):
    plan = {
        "fixture": True,
        "cases": [{"prediction": "page.md"}],
        "unique_pages": 1,
        "dataset": "test",
        "dataset_revision": "revision",
        "evaluator": {"commit": "commit"},
    }
    summarize(tmp_path, plan, tmp_path, {}, "basic")
    assert "NÃO É SCORE DO ACESSILIA" in (tmp_path / "report.md").read_text()
    assert read(tmp_path / "summary.json")["overall"] is None


@pytest.mark.parametrize("profile,timeout", [("unknown", 10), ("basic", 0)])
def test_invalid_evaluation_parameters_fail_before_creating_artifacts(workspace, profile, timeout):
    with pytest.raises(ValueError):
        evaluate(workspace, "nonexistent", profile, timeout)
    assert not workspace.run_dir("nonexistent").exists()


@pytest.mark.parametrize(
    "error", ["Error: Cannot find module 'match-at'", "CDM sample failed: rendering"]
)
def test_cdm_dependency_failures_cannot_be_reported_as_quality_zero(tmp_path, error):
    (tmp_path / "evaluator.log").write_text(error, encoding="utf-8")
    with pytest.raises(ValueError, match="CDM contém falhas"):
        validate_cdm(tmp_path, {})


def test_cdm_missing_reference_rendering_is_rejected(tmp_path):
    from acessilia_benchmark.io import write

    (tmp_path / "evaluator.log").write_text("CDM: 0", encoding="utf-8")
    write(tmp_path / "result/sample_display_formula_result.json", [{"gt": "x", "pred": "x"}])
    with pytest.raises(ValueError, match="não renderizou"):
        validate_cdm(tmp_path, {"display_formula": {"all": {"CDM": {"all": 0}}}})


def test_overall_score_calculation():
    metrics = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
        "table": {"page": {"TEDS": {"ALL": 0.95}}},
        "display_formula": {"page": {"CDM": {"ALL": 0.90}}},
    }
    # ((1 - 0.1)*100 + 95 + 90) / 3 = (90 + 95 + 90) / 3 = 91.666666...
    assert compute_overall(metrics) == pytest.approx(91.66666666666667)


def test_overall_missing_components_returns_none():
    assert compute_overall({}) is None
    assert (
        compute_overall(
            {
                "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
                "table": {"page": {"TEDS": {"ALL": 0.95}}},
            }
        )
        is None
    )


def test_full_profile_computes_overall_and_renders_report(tmp_path):
    plan = {
        "fixture": True,
        "cases": [{"prediction": "page.md"}],
        "unique_pages": 1,
        "dataset": "omnidocbench",
        "dataset_revision": "revision",
        "evaluator": {"commit": "commit"},
    }
    metrics = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
        "table": {"all": {"TEDS": {"all": 1.0}}, "page": {"TEDS": {"ALL": 1.0}}},
        "display_formula": {"all": {"CDM": {"all": 1.0}}, "page": {"CDM": {"ALL": 1.0}}},
    }
    summarize(tmp_path, plan, tmp_path, metrics, "full")
    summary = read(tmp_path / "summary.json")
    expected = ((1 - 0.1) * 100 + 100 + 100) / 3.0
    assert summary["overall"] == pytest.approx(expected)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Score Overall" in report
    assert f"**Overall: {expected:.4f}**" in report
