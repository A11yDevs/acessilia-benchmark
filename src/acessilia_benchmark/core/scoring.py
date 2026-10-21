"""Dataset-specific, auditable Overall aggregation from official evaluator outputs."""

import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

from ..io import read

OMNI_SOURCE = "OmniDocBench/src/runtime/eval_report.py::build_notebook_metric_summary"
DR_SOURCE = "https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench#supported-tasks"


def unit_score(value, name):
    """Evaluator JSON uses fractions, never infer percentage units from magnitude."""
    if value is None or (
        isinstance(value, str) and value.lower() in {"nan", "infinity", "-infinity"}
    ):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Métrica inválida: {name}={value!r}")
    if not math.isfinite(value):
        return None
    if not 0 <= value <= 1:
        raise ValueError(f"Métrica fora de [0,1]: {name}={value}")
    return float(value)


def metric_at(metrics, *keys):
    value = metrics
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def omni_components(metrics):
    # Exact paths selected by the pinned official notebook summary. No block/global fallback.
    paths = {
        "text_edit": ("text_block", "all", "Edit_dist", "ALL_page_avg"),
        "table_teds": ("table", "page", "TEDS", "ALL"),
        "formula_cdm": ("display_formula", "page", "CDM", "ALL"),
    }
    return {key: unit_score(metric_at(metrics, *path), key) for key, path in paths.items()}


def compute_overall(metrics):
    """OmniDocBench notebook aggregate (0–100); None when a required component is absent."""
    if not isinstance(metrics, dict):
        return None
    parts = omni_components(metrics)
    if any(value is None for value in parts.values()):
        return None
    return 100 * ((1 - parts["text_edit"]) + parts["table_teds"] + parts["formula_cdm"]) / 3


def records(artifacts, component):
    files = list((artifacts / "result").glob(f"*_{component}_result.json"))
    if len(files) != 1:
        raise ValueError(f"Artefato de componente ausente/ambíguo: {component}")
    return read(files[0])


def dr_case_scores(artifacts, cases):
    """Apply Dr's available-component composition to the pinned multipage window unit."""
    expected = {Path(case["prediction"]).stem: case["id"] for case in cases}
    if len(expected) != len(cases):
        raise ValueError("IDs de janela ambíguos para agregar Overall.")
    scores = {key: {} for key in expected}
    for component in ("text_block", "reading_order"):
        rows = records(artifacts, component)
        files = list((artifacts / "result").glob(f"*_{component}_per_page_edit.json"))
        if rows and len(files) != 1:
            raise ValueError(f"Distâncias por janela ausentes: {component}")
        values = read(files[0]) if len(files) == 1 else {}
        row_ids = {Path(str(row["img_id"])).stem for row in rows}
        value_ids = {Path(image).stem for image in values}
        if row_ids != value_ids:
            raise ValueError(f"Cobertura de distâncias por janela divergente: {component}")
        for image, value in values.items():
            key = Path(image).stem
            if key not in expected:
                raise ValueError(f"Janela inesperada: {image}")
            distance = unit_score(value, component)
            if distance is None:
                raise ValueError(f"Distância não finita em janela pontuada: {image}")
            scores[key][component] = 100 * (1 - distance)
    for component, metric in (("table", "TEDS"), ("display_formula", "CDM")):
        grouped = defaultdict(list)
        for row in records(artifacts, component):
            key = Path(str(row["img_id"])).stem
            if key not in expected:
                raise ValueError(f"Janela inesperada: {row['img_id']}")
            value = unit_score(row.get("metric", {}).get(metric), f"{component}/{metric}")
            if value is None:
                raise ValueError(f"Métrica ausente/não finita em bloco pontuado: {component}/{key}")
            grouped[key].append(value)
        for key, values in grouped.items():
            scores[key][component] = 100 * mean(values)
    return {
        expected[key]: {"components": parts, "overall": mean(parts.values()) if parts else None}
        for key, parts in scores.items()
    }


def overall_details(metrics, dataset, profile, artifacts, cases):
    details = {"value": None, "scale": "0–100", "leaderboard_comparable": False}
    if profile != "full":
        return dict(details, protocol=None, reason="Perfil basic não calcula CDM; use full.")
    if dataset == "omnidocbench":
        parts = omni_components(metrics)
        value = compute_overall(metrics)
        return dict(
            details,
            value=value,
            protocol="omnidocbench-notebook-three-components",
            source=OMNI_SOURCE,
            components=parts,
            reason="Faltam métricas finitas: " + ", ".join(k for k, v in parts.items() if v is None)
            if value is None
            else None,
        )
    if dataset == "drdocbench-dev":
        scores = dr_case_scores(artifacts, cases)
        valid = [case["overall"] for case in scores.values() if case["overall"] is not None]
        return dict(
            details,
            value=mean(valid) if valid else None,
            protocol="drdocbench-available-components-per-window",
            source=DR_SOURCE,
            unit="single-page window"
            if all(len(c.get("images", [])) == 1 for c in cases)
            else "two-page window; not the challenge single-page unit",
            case_scores=scores,
            excluded_cases=[key for key, case in scores.items() if case["overall"] is None],
            reason=None if valid else "Nenhuma janela com componentes pontuados.",
        )
    return dict(details, protocol=None, reason=f"Protocolo Overall não definido para {dataset}.")
