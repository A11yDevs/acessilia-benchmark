"""Difficulty-balanced OmniDocBench selection and original-record mapping."""

import hashlib
import sys
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from acessilia_benchmark import cli
from acessilia_benchmark.core.runs import load_plan, prepare
from acessilia_benchmark.core.selection import (
    DIFFICULTY_QUOTAS,
    POLICY,
    PUBLIC_ORDER,
    validate_manifest,
)
from acessilia_benchmark.io import digest, read, write
from acessilia_benchmark.reporting import _selection_group_summary
from acessilia_benchmark.services.comparison import _metrics, _selection_group_coverage


def _selection_manifest(snapshot, selection_path):
    categories = {}
    pages = []
    index = 0
    for category in PUBLIC_ORDER:
        rows = []
        for band, count in DIFFICULTY_QUOTAS.items():
            for _ in range(count):
                image_name = f"page-{index}.png"
                image = snapshot / "images" / image_name
                image.parent.mkdir(parents=True, exist_ok=True)
                with Image.new("RGB", (20, 30), "white") as frame:
                    frame.save(image)
                layout = "double_column" if category == "layout_complexo" else "single_column"
                attributes = {
                    "data_source": "fixture_source",
                    "language": "english",
                    "layout": layout,
                    "special_issue": [],
                    "subset": "fixture",
                }
                blocks = [{"category_type": "text_block", "order": 0, "text": "reference"}]
                row = {
                    "id": Path(image_name).stem,
                    "image": image_name,
                    "original_image_path": image_name,
                    "original_record_index": index,
                    "page_no": index,
                    "document_group": None,
                    "difficulty_band": band,
                    "difficulty_score": float(index),
                    "data_source": "fixture_source",
                    "language": "english",
                    "layout": layout,
                    "special_issue": [],
                    "subset": "fixture",
                    "fuzzy_scan": category == "ocr_dificil",
                    "handwritten_note": False,
                    "rotated_text": False,
                    "colorful_background": False,
                    "watermark": False,
                    "tables": int(category == "tabelas"),
                    "display_formulas": int(category == "formulas"),
                    "inline_formulas": 0,
                    "text_blocks": 2,
                    "block_count": 2,
                    "captions": 0,
                    "reading_order_blocks": 2,
                    "features": [],
                }
                if category == "tabelas":
                    blocks.append({"category_type": "table", "order": 1})
                elif category == "formulas":
                    blocks.append({"category_type": "equation_isolated", "order": 1})
                pages.append(
                    {
                        "page_info": {
                            "image_path": image_name,
                            "page_no": index,
                            "page_attribute": attributes,
                        },
                        "layout_dets": blocks,
                    }
                )
                rows.append(row)
                index += 1
        categories[category] = rows

    annotation_path = snapshot / "OmniDocBench.json"
    write(annotation_path, pages)
    layout_counts = dict(
        sorted(Counter(page["page_info"]["page_attribute"]["layout"] for page in pages).items())
    )
    case_ids = [row["id"] for category in PUBLIC_ORDER for row in categories[category]]
    source_counts = {"fixture_source": 80}
    language_counts = {"english": 80}
    sample_layout_counts = dict(
        sorted(Counter(row["layout"] for rows in categories.values() for row in rows).items())
    )
    manifest = {
        "schema_version": 3,
        "selection_policy": POLICY,
        "dataset": "omnidocbench",
        "dataset_revision": "fixture",
        "annotation_sha256": digest(annotation_path),
        "seed": 42,
        "population_size": 80,
        "population_by_source": source_counts,
        "sample_by_source": source_counts,
        "population_by_language": language_counts,
        "sample_by_language": language_counts,
        "population_by_source_language": {"fixture_source|english": 80},
        "sample_by_source_language": {"fixture_source|english": 80},
        "population_by_layout": layout_counts,
        "sample_by_layout": sample_layout_counts,
        "eligible_candidates_by_category": {
            "texto_comum": 32,
            "ocr_dificil": 16,
            "tabelas": 16,
            "formulas": 16,
            "layout_complexo": 16,
        },
        "difficulty_quotas": DIFFICULTY_QUOTAS,
        "category_quotas": dict.fromkeys(PUBLIC_ORDER, 16),
        "difficulty_counts": {category: dict(DIFFICULTY_QUOTAS) for category in PUBLIC_ORDER},
        "representativeness": {
            "method": "marginal_total_variation_distance",
            "dimensions": {
                "source": 0.0,
                "language": 0.0,
                "layout": 0.0,
                "source_language": 0.0,
            },
        },
        "count": 80,
        "selection_sha256": hashlib.sha256("\n".join(case_ids).encode()).hexdigest(),
        "category_order": list(PUBLIC_ORDER),
        "case_ids": case_ids,
        "categories": categories,
    }
    write(selection_path, manifest)
    return manifest


def _refresh_download_manifest(workspace, snapshot, spec):
    files = [
        {
            "path": path.relative_to(snapshot).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in sorted(snapshot.rglob("*"))
        if path.is_file() and path.name != "download-manifest.json"
    ]
    spec["expected_files"] = len(files)
    spec["expected_bytes"] = sum(row["bytes"] for row in files)
    catalog = read(workspace.root / "datasets/registry.json")
    catalog["datasets"]["omnidocbench"].update(spec)
    write(workspace.root / "datasets/registry.json", catalog)
    write(
        snapshot / "download-manifest.json",
        {
            "schema_version": 1,
            "dataset_id": "omnidocbench",
            "repo_id": spec["repo_id"],
            "revision": "fixture",
            "split": "dev",
            "files": files,
        },
    )


def test_selection_manifest_is_unique_difficulty_balanced_and_mapped(
    workspace, dataset_factory, tmp_path
):
    snapshot, spec = dataset_factory()
    selection_path = tmp_path / "selection.json"
    manifest = _selection_manifest(snapshot, selection_path)
    pages = read(snapshot / "OmniDocBench.json")
    cases = [
        {
            "id": Path(page["page_info"]["image_path"]).stem,
            "images": [page["page_info"]["image_path"]],
        }
        for page in pages
    ]
    rows = validate_manifest(
        manifest,
        "omnidocbench",
        spec["revision"],
        digest(snapshot / "OmniDocBench.json"),
        cases,
        pages,
    )
    assert len(rows) == 80
    assert len({row[1]["original_record_index"] for row in rows.values()}) == 80
    assert Counter(category for category, _ in rows.values()) == Counter(
        dict.fromkeys(PUBLIC_ORDER, 16)
    )
    assert manifest["difficulty_counts"] == {
        category: dict(DIFFICULTY_QUOTAS) for category in PUBLIC_ORDER
    }

    corrupted = read(selection_path)
    corrupted_row = corrupted["categories"][PUBLIC_ORDER[0]][0]
    corrupted_row["original_image_path"] = f"elsewhere/{corrupted_row['image']}"
    with pytest.raises(ValueError, match="Mapeamento ao registro original diverge"):
        validate_manifest(
            corrupted,
            "omnidocbench",
            spec["revision"],
            digest(snapshot / "OmniDocBench.json"),
            cases,
            pages,
        )

    duplicated = read(selection_path)
    duplicated["categories"][PUBLIC_ORDER[1]][0]["original_record_index"] = 0
    with pytest.raises(ValueError, match="Índice original repetido"):
        validate_manifest(
            duplicated,
            "omnidocbench",
            spec["revision"],
            digest(snapshot / "OmniDocBench.json"),
        )


def test_prepare_copies_selection_and_seals_case_grouping(workspace, dataset_factory, tmp_path):
    snapshot, spec = dataset_factory()
    selection_path = tmp_path / "selection.json"
    manifest = _selection_manifest(snapshot, selection_path)
    _refresh_download_manifest(workspace, snapshot, spec)

    destination, plan = prepare(
        workspace,
        "omnidocbench",
        "omni80",
        workspace.data,
        0,
        42,
        selection_file=selection_path,
    )

    assert len(plan["cases"]) == 80
    assert [case["id"] for case in plan["cases"]] == manifest["case_ids"]
    assert plan["selection"]["selection_sha256"] == manifest["selection_sha256"]
    assert digest(destination / "selection.json") == plan["selection"]["manifest_sha256"]
    assert Counter(case["selection_group"]["category"] for case in plan["cases"]) == Counter(
        dict.fromkeys(PUBLIC_ORDER, 16)
    )
    assert Counter(case["selection_group"]["difficulty_band"] for case in plan["cases"]) == {
        "facil": 20,
        "medio": 30,
        "dificil": 30,
    }
    load_plan(workspace, "omni80")

    (destination / "selection.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Manifesto de seleção ausente ou alterado"):
        load_plan(workspace, "omni80")


@pytest.mark.parametrize("kwargs", [{"limit": 1}, {"fixture": True}, {"seed": 7}])
def test_fixed_selection_rejects_conflicting_sampling_options(
    workspace, dataset_factory, tmp_path, kwargs
):
    snapshot, spec = dataset_factory()
    selection_path = tmp_path / "selection.json"
    _selection_manifest(snapshot, selection_path)
    _refresh_download_manifest(workspace, snapshot, spec)
    with pytest.raises(ValueError):
        prepare(
            workspace,
            "omnidocbench",
            "invalid",
            workspace.data,
            kwargs.pop("limit", 0),
            kwargs.pop("seed", 42),
            selection_file=selection_path,
            **kwargs,
        )
    assert not workspace.run_dir("invalid").exists()


def test_prepare_cli_forwards_selection_file(workspace, dataset_factory, tmp_path, monkeypatch):
    dataset_factory()
    selection_path = tmp_path / "selection.json"
    selection_path.write_text("{}", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(cli.Workspace, "discover", lambda: workspace)
    monkeypatch.setattr(cli, "prepare", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bench",
            "prepare",
            "omnidocbench",
            "--run",
            "cli-run",
            "--selection-file",
            str(selection_path),
        ],
    )

    cli.main()

    assert captured["selection_file"] == selection_path


def test_group_report_uses_per_page_means_and_tracks_missing_coverage(tmp_path):
    cases = []
    for index, category in enumerate(PUBLIC_ORDER):
        cases.append(
            {
                "id": f"page-{index}",
                "selection_group": {
                    "category": category,
                    "difficulty_band": "facil",
                    "data_source": "fixture_source",
                    "language": "english",
                    "layout": "single_column",
                    "document_group": "doc-a" if index < 2 else None,
                    "tables": int(category == "tabelas"),
                    "display_formulas": int(category == "formulas"),
                    "text_blocks": 1,
                    "reading_order_blocks": 1,
                },
            }
        )
    plan = {
        "selection": {
            "category_order": list(PUBLIC_ORDER),
            "eligible_candidates_by_category": dict.fromkeys(PUBLIC_ORDER, 20),
        },
        "cases": cases,
    }
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    write(result_dir / "run_text_block_per_page_edit.json", {"page-0.png": 0.2})
    write(
        result_dir / "run_table_result.json",
        [{"img_id": "page-2.png", "metric": {"TEDS": 0.8}}],
    )
    write(
        result_dir / "run_display_formula_result.json",
        [{"img_id": "page-3.png", "metric": {"CDM": 0.7}}],
    )

    summary = _selection_group_summary(plan, tmp_path)

    assert summary["texto_comum"]["metrics"]["text_block"]["Edit_dist"]["value"] == 0.2
    coverage = summary["texto_comum"]["metrics"]["text_block"]["Edit_dist"]["coverage"]
    assert coverage["expected_pages"] == 1
    assert coverage["applicable_pages"] == 1
    assert coverage["scored_pages"] == 1
    assert coverage["unscored_applicable_pages"] == []
    assert summary["tabelas"]["metrics"]["table"]["TEDS"]["value"] == 0.8
    assert summary["formulas"]["metrics"]["display_formula"]["CDM"]["value"] == 0.7
    assert summary["texto_comum"]["inferred_document_groups"] == 1


def test_comparison_metrics_include_group_values_and_coverage():
    summary = {
        "overall": None,
        "metrics": {},
        "selection_groups": {
            "tabelas": {
                "metrics": {
                    "table": {
                        "TEDS": {
                            "value": 0.8,
                            "coverage": {"applicable_pages": 2, "scored_pages": 2},
                        }
                    }
                }
            }
        },
    }
    assert _metrics(summary)["selection_group/tabelas/table/TEDS"] == (0.8, 1)
    assert _selection_group_coverage(summary)["tabelas"]["table"]["TEDS"] == {
        "applicable_pages": 2,
        "scored_pages": 2,
    }
