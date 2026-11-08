"""Normalize metric results and build quantitative and qualitative reports."""

import json
import math
import os
from pathlib import Path
from urllib.parse import quote

from .core.scoring import overall_details
from .io import digest, local_path, read, write


def processing_assessment(
    destination, plan, origin, rows=None, formula_page_stems=(), formula_diagnostic_cases=()
):
    """Surface reported diagnostics without treating absent warnings as proof of success."""
    if origin != "acessilia":
        return {"status": "not_available", "cases": [], "origin": origin}
    by_id = {row["id"]: row for row in rows} if rows is not None else None
    cases = []
    for case in plan["cases"]:
        row = by_id.get(case["id"]) if by_id is not None else None
        if by_id is not None and (row is None or row.get("status") != "ok"):
            continue
        path = local_path(destination / "predictions", case["prediction"]).with_suffix(
            ".metadata.json"
        )
        if not path.is_file():
            if row is not None and row.get("metadata_sha256") is not None:
                raise ValueError(f"Metadados de inferência ausentes: {case['id']}")
            cases.append({"id": case["id"], "status": "unknown"})
            continue
        if row is not None and digest(path) != row.get("metadata_sha256"):
            raise ValueError(f"Metadados de inferência alterados: {case['id']}")
        metadata = read(path)
        warnings = metadata.get("technical_warnings")
        valid_warnings = isinstance(warnings, list) and all(
            isinstance(item, str) for item in warnings
        )
        diagnostics = metadata.get("processing_diagnostics")
        signals = []
        case_stems = {
            Path(case["prediction"]).stem,
            Path(str(case["id"])).stem,
            *(Path(image).stem for image in case.get("images", [])),
        }
        formula_diagnostics_missing = (
            case["id"] in formula_diagnostic_cases
            or any(
                _same_page_stem(case_stem, formula_stem)
                for case_stem in case_stems
                for formula_stem in formula_page_stems
            )
        ) and (
            not isinstance(diagnostics, dict) or diagnostics.get("pddl_formula_diagnostics") is None
        )
        if formula_diagnostics_missing:
            signals.append("formula_diagnostics_unavailable")
        if isinstance(diagnostics, dict):
            if diagnostics.get("pddl_unsatisfied_obligations"):
                signals.append("unsatisfied_obligations")
            formula = diagnostics.get("pddl_formula_diagnostics")
            if isinstance(formula, dict):
                if _positive_count(formula.get("vision_fallbacks")):
                    signals.append("formula_vision_fallback")
                if _positive_count(formula.get("unrecognized")):
                    signals.append("formulas_unrecognized")
            limits = diagnostics.get("pddl_external_provider_limits")
            if isinstance(limits, dict) and any(
                _positive_count(value) for value in limits.values()
            ):
                signals.append("external_provider_limits")
            visual = diagnostics.get("pddl_visual_failures")
            if isinstance(visual, dict) and any(
                isinstance(counts, dict) and any(counts.values()) for counts in visual.values()
            ):
                signals.append("visual_failures")
            if diagnostics.get("pddl_extraction_degraded") is True:
                signals.append("extraction_degraded")
            fusion = diagnostics.get("pddl_fusion")
            if isinstance(fusion, dict) and fusion.get("status") == "degraded":
                signals.append("degraded_fusion")
            inspection = diagnostics.get("pddl_media_inspection")
            if isinstance(inspection, dict) and inspection.get("status") == "failed":
                signals.append("media_inspection_failed")
        cases.append(
            {
                "id": case["id"],
                "status": (
                    "unknown"
                    if formula_diagnostics_missing
                    else "reported_warnings"
                    if (valid_warnings and warnings)
                    or any(signal != "formula_diagnostics_unavailable" for signal in signals)
                    else "no_reported_warnings"
                    if valid_warnings
                    else "unknown"
                ),
                "warnings": warnings if valid_warnings else None,
                "signals": signals,
                "diagnostics": diagnostics if isinstance(diagnostics, dict) else None,
            }
        )
    status = (
        "unknown"
        if len(cases) != len(plan["cases"]) or any(c["status"] == "unknown" for c in cases)
        else "reported_warnings"
        if any(c["status"] == "reported_warnings" for c in cases)
        else "no_reported_warnings"
    )
    return {"status": status, "cases": cases, "origin": origin}


def summarize(destination, plan, artifacts, metrics, profile):
    manifest_path = destination / "prediction-manifest.json"
    origin = read(manifest_path)["origin"] if manifest_path.is_file() else {"kind": "unknown"}
    aggregation = overall_details(metrics, plan["dataset"], profile, artifacts, plan["cases"])
    overall = aggregation["value"]
    summary = {
        "fixture": plan["fixture"],
        "profile": profile,
        "overall": overall,
        "overall_details": aggregation,
        "prediction_origin": origin,
        "coverage": {"cases": len(plan["cases"]), "unique_pages": plan["unique_pages"]},
        "metrics": {
            name: metrics.get(name, {}).get("all", {})
            for name in ("text_block", "table", "display_formula", "reading_order")
        },
    }
    summary["processing"] = processing_assessment(
        destination,
        plan,
        origin["kind"],
        formula_page_stems=_formula_page_stems(artifacts),
    )
    summary["evaluator_diagnostics"] = {
        name: value for name, value in metrics.items() if name not in summary["metrics"]
    }
    if (destination / "system.json").is_file():
        summary["system"] = read(destination / "system.json")
    timing_path = destination / "timings.jsonl"
    if timing_path.exists() and origin["kind"] == "acessilia":
        timings = [json.loads(line) for line in timing_path.read_text().splitlines()]
        seconds = sorted(row["seconds"] for row in timings)
        if not seconds:
            raise ValueError("Tempos de inferência vazios.")
        total = sum(seconds)
        summary["runtime"] = {
            "cases": len(timings),
            "failures": sum(t["status"] != "ok" for t in timings),
            "total_seconds": total,
            "p50_seconds_per_window": seconds[math.ceil(len(seconds) * 0.5) - 1],
            "p95_seconds_per_window": seconds[math.ceil(len(seconds) * 0.95) - 1],
            "processed_pages_per_minute": sum(t["pages"] for t in timings) * 60 / total
            if total > 0
            else None,
            "failures_by_kind": _failure_counts(timings),
        }
    worst = []
    observed = set()
    block_counts = {}
    for file in (artifacts / "result").glob("*_result.json"):
        if file.name.endswith("_metric_result.json"):
            continue
        records = read(file)
        if not isinstance(records, list):
            continue
        block_counts[file.stem] = len(records)
        for record in records:
            observed.add(Path(str(record.get("img_id", ""))).stem)
            values = record.get("metric") or {}
            errors = [
                float(values[key])
                for key in ("Edit_dist",)
                if isinstance(values.get(key), (int, float))
            ]
            for metric in ("TEDS", "CDM"):
                if isinstance(values.get(metric), (int, float)):
                    errors.append(1 - float(values[metric]))
            errors = [error for error in errors if math.isfinite(error)]
            if errors:
                worst.append(
                    {
                        "component": file.stem,
                        "id": record.get("img_id"),
                        "error": max(errors),
                        "gt": record.get("gt", ""),
                        "pred": record.get("pred", ""),
                    }
                )
    summary["worst_blocks"] = sorted(worst, key=lambda item: (-item["error"], str(item["id"])))[:10]
    expected = {Path(case["prediction"]).stem for case in plan["cases"]}
    summary["coverage"].update(
        scored_cases=len(expected & observed), unscored_cases=sorted(expected - observed)
    )
    summary["evaluated_blocks"] = block_counts
    summary = normalize_numbers(summary)
    write(artifacts / "summary.json", summary)
    label = (
        "AUTOVERIFICAÇÃO COM REFERÊNCIAS — NÃO É SCORE DO ACESSILIA"
        if plan["fixture"]
        else "Avaliação manual do Acessilia"
        if origin["kind"] == "acessilia"
        else "Avaliação de previsões importadas"
    )
    lines = [
        f"# {label}",
        "",
        f"Dataset: {plan['dataset']} @ {plan['dataset_revision']}",
        f"Avaliador: {plan['evaluator']['commit']}",
        f"Cobertura: {len(plan['cases'])} casos; {plan['unique_pages']} páginas únicas.",
        "Perfil basic: sem CDM e sem score Overall comparável ao ranking oficial."
        if profile == "basic"
        else (
            f"Perfil full: Overall local = {overall:.4f} (0–100)."
            if overall is not None
            else "Perfil full: Overall indisponível. " + aggregation["reason"]
        ),
        "",
        "## Métricas",
        "",
        "```json",
        json.dumps(summary["metrics"], indent=2, ensure_ascii=False),
        "```",
    ]
    lines[5:5] = [
        "",
        "## Diagnóstico do processamento",
        "",
        "Avisos são sinais para revisão, não uma classificação automática de falha. "
        "Ausência de avisos não comprova processamento completo: o Core pode não "
        "propagar todas as falhas. Em páginas com fórmula, a ausência de "
        "pddl_formula_diagnostics mantém o processamento como unknown. As métricas "
        "medem o arquivo produzido.",
        "",
        "```json",
        json.dumps(summary["processing"], indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    if overall is not None:
        lines += [
            "",
            "## Score Overall",
            "",
            f"**Overall: {overall:.4f}**",
            "",
            "Protocolo: `"
            + aggregation["protocol"]
            + "`. Resultado local; não é posição no ranking.",
            "",
            "```json",
            json.dumps(aggregation, indent=2, ensure_ascii=False),
            "```",
        ]
    if "runtime" in summary:
        lines += [
            "",
            "## Tempo de inferência",
            "",
            "Inclui startup do processo, cache e serviços; não mede GPU-hora.",
            "",
            "```json",
            json.dumps(summary["runtime"], indent=2),
            "```",
        ]
    lines += [
        "",
        f"Casos com pares pontuados: {summary['coverage']['scored_cases']}.",
        "Métricas nulas/vazias significam ausência de elementos ou resultado não finito, nunca score zero.",
    ]
    if summary["coverage"]["unscored_cases"]:
        lines += [
            "",
            "Casos sem pares pontuados: " + ", ".join(summary["coverage"]["unscored_cases"]),
        ]
    lines += [
        "",
        "## Blocos com maiores erros",
        "",
        "Triagem por métrica; severidade para o leitor exige revisão humana.",
    ]
    for block in summary["worst_blocks"]:
        lines += ["", f"### {block['id']} — {block['component']} — erro {block['error']:.4f}", ""]
        for case in plan["cases"]:
            if Path(case["prediction"]).stem == Path(str(block["id"])).stem:
                for number, image in enumerate(case["images"], 1):
                    link = quote(os.path.relpath(image, artifacts), safe="/")
                    lines.append(f"[Imagem {number}]({link})")
                break
        lines += ["", "Referência:", ""]
        lines += ["    " + line for line in str(block["gt"]).splitlines()]
        lines += ["", "Previsão:", ""] + ["    " + line for line in str(block["pred"]).splitlines()]
    (artifacts / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_numbers(value):
    """Keep JSON standard-compliant and distinguish non-applicable metrics from zero."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str) and value in {"NaN", "nan", "Infinity", "-Infinity"}:
        return None
    if isinstance(value, dict):
        return {key: normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_numbers(item) for item in value]
    return value


def summarize_runtime(destination, plan):
    """Report measured attempts, including failed/partial inference, without GT scores."""
    from .io import digest, seal, verify_seal

    evidence_path = destination / "inference.json"
    if not evidence_path.is_file():
        raise ValueError("Tempos reais do Acessilia ausentes; execute predict.")
    verify_seal(evidence_path)
    evidence = read(evidence_path)
    if evidence.get("plan_sha256") != digest(destination / "plan.json"):
        raise ValueError("Evidência de inferência pertence a outro plano.")
    rows = evidence["cases"]
    timings = [
        json.loads(line) for line in (destination / "timings.jsonl").read_text().splitlines()
    ]
    if timings != rows:
        raise ValueError("Tempos divergentes da evidência de inferência selada.")
    expected = {case["id"]: len(case["images"]) for case in plan["cases"]}
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)) or not set(ids) <= expected.keys():
        raise ValueError("Casos de inferência inválidos.")
    if any(
        row["status"] not in {"ok", "failed", "timeout"}
        or not math.isfinite(row["seconds"])
        or row["seconds"] < 0
        or row["pages"] != expected[row["id"]]
        for row in rows
    ):
        raise ValueError("Medições de inferência inválidas.")
    seconds = sorted(row["seconds"] for row in rows)
    total = sum(seconds)
    successful = [row for row in rows if row["status"] == "ok"]
    attempted_pages = sum(row["pages"] for row in rows)
    successful_pages = sum(row["pages"] for row in successful)
    summary = {
        "dataset": plan["dataset"],
        "dataset_revision": plan["dataset_revision"],
        "profile": "runtime",
        "overall": None,
        "quality_metrics": None,
        "quality_reason": "Perfil de execução sem avaliação de referências.",
        "status": evidence["status"],
        "system": read(destination / "system.json")
        if (destination / "system.json").is_file()
        else None,
        "plan_sha256": digest(destination / "plan.json"),
        "inference_sha256": digest(evidence_path),
        "processing": processing_assessment(
            destination,
            plan,
            "acessilia",
            rows,
            formula_diagnostic_cases=_runtime_formula_cases(destination, plan),
        ),
        "coverage": {
            "planned_cases": len(expected),
            "attempted_cases": len(rows),
            "unattempted_cases": len(expected) - len(rows),
            "unique_pages": plan["unique_pages"],
        },
        "runtime": {
            "inference_calls": sum(row.get("attempts", 1) for row in rows),
            "failed_calls": sum(
                row.get("failed_attempts", int(row["status"] != "ok")) for row in rows
            ),
            "successful_cases": len(successful),
            "failures": len(rows) - len(successful),
            "timeouts": sum(row["status"] == "timeout" for row in rows),
            "success_rate": len(successful) / len(rows) if rows else None,
            "total_seconds": total,
            "mean_seconds_per_window": total / len(rows) if rows else None,
            "p50_seconds_per_window": seconds[math.ceil(len(rows) * 0.5) - 1] if rows else None,
            "p95_seconds_per_window": seconds[math.ceil(len(rows) * 0.95) - 1] if rows else None,
            "attempted_pages": attempted_pages,
            "successful_page_occurrences": successful_pages,
            "successful_pages_per_minute": successful_pages * 60 / total if total else None,
            "failures_by_kind": _failure_counts(rows),
        },
    }
    artifacts = destination / "runtime-report"
    write(artifacts / "summary.json", summary)
    (artifacts / "report.md").write_text(
        "# Execução do Acessilia\n\n"
        f"Dataset: {plan['dataset']} @ {plan['dataset_revision']}\n\n"
        "Sem métricas de qualidade ou Overall neste perfil.\n\n"
        "Diagnósticos de processamento estão incluídos abaixo; ausência de avisos "
        "não comprova processamento completo. Fórmulas sem diagnóstico do Core "
        "permanecem unknown. Sem referências para identificar fórmulas, a ausência "
        "desse diagnóstico também mantém o estado unknown.\n\n"
        "Tempos incluem startup do processo, preparação da entrada, cache e serviços; "
        "não medem apenas o modelo nem GPU-hora. Tempos e percentis acumulam todas "
        "as tentativas por caso, incluindo falhas, timeouts e retomadas. "
        "`failures_by_kind` classifica falhas por assinaturas conhecidas nos logs, sem expor o texto bruto; "
        "assinaturas não reconhecidas ficam como `process_failed`. "
        "Páginas na vazão contam ocorrências nas janelas; janelas vizinhas podem "
        "compartilhar páginas. Falhas consomem tempo, mas não contam na vazão de sucesso.\n\n"
        + "```json\n"
        + json.dumps(summary, indent=2, ensure_ascii=False)
        + "\n```\n",
        encoding="utf-8",
    )
    seal(artifacts / "summary.json")


def _runtime_formula_cases(destination, plan):
    """Require diagnostics for formula or unlabelled cases, before evaluation exists."""
    references = plan.get("reference_sha256", {})

    def pages(path):
        expected = references.get(str(path))
        if expected is None:
            return None
        if digest(path) != expected:
            raise ValueError(f"Referência alterada: {path}")
        data = read(path)
        return data if isinstance(data, list) else None

    omni_pages = (
        pages(destination / "ground-truth.json") if plan["dataset"] == "omnidocbench" else None
    )
    by_image = {
        Path(page.get("page_info", {}).get("image_path", "")).name: page
        for page in omni_pages or []
        if isinstance(page, dict)
    }
    required = set()
    for case in plan["cases"]:
        if plan["dataset"] == "omnidocbench":
            groups = [[by_image.get(Path(image).name)] for image in case["images"]]
        else:
            groups = [pages(Path(path)) for path in case.get("references", [])]
        if (
            len(groups) != len(case["images"])
            or not groups
            or any(group is None for group in groups)
        ):
            required.add(case["id"])
            continue
        for page in (page for group in groups for page in group):
            blocks = page.get("layout_dets") if isinstance(page, dict) else None
            if not isinstance(blocks, list) or any(
                not isinstance(block, dict) or block.get("category_type") == "equation_isolated"
                for block in blocks
            ):
                required.add(case["id"])
                break
    return required


def _formula_page_stems(artifacts):
    """Return page IDs with formula references in the official evaluator output."""
    files = list((artifacts / "result").glob("*_display_formula_result.json"))
    if len(files) != 1:
        return set()
    records = read(files[0])
    if not isinstance(records, list):
        return set()
    return {
        Path(str(row.get("img_id", ""))).stem
        for row in records
        if isinstance(row, dict) and str(row.get("gt", "")).strip()
    }


def _same_page_stem(case_stem, formula_stem):
    """Match evaluator page IDs to image stems even when a document prefix differs."""
    if not case_stem or not formula_stem:
        return False
    if case_stem == formula_stem:
        return True
    return any(
        longer.endswith(separator + shorter)
        for longer, shorter in ((case_stem, formula_stem), (formula_stem, case_stem))
        for separator in ("_", "-", "/")
    )


def _positive_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _failure_counts(rows):
    """Aggregate failed attempts, with conservative compatibility for older rows."""
    counts = {
        "benchmark_timeout": 0,
        "provider_timeout": 0,
        "provider_unavailable": 0,
        "process_failed": 0,
    }
    for row in rows:
        kinds = row.get("failure_kinds")
        if isinstance(kinds, dict):
            for kind, count in kinds.items():
                if kind in counts and isinstance(count, int) and not isinstance(count, bool):
                    counts[kind] += max(0, count)
            continue
        # Older evidence only distinguished outer benchmark timeouts.
        failed_attempts = row.get("failed_attempts", int(row.get("status") != "ok"))
        if not isinstance(failed_attempts, int) or isinstance(failed_attempts, bool):
            failed_attempts = int(row.get("status") != "ok")
        if row.get("status") == "timeout" and failed_attempts > 0:
            counts["benchmark_timeout"] += 1
            failed_attempts -= 1
        counts["process_failed"] += max(0, failed_attempts)
    return counts
