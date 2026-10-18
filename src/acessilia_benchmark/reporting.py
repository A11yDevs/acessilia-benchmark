"""Normalize metric results and build quantitative and qualitative reports."""

import json
import math
import os
from pathlib import Path
from urllib.parse import quote

from .core.scoring import overall_details
from .io import read, write


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
        "plan_sha256": digest(destination / "plan.json"),
        "inference_sha256": digest(evidence_path),
        "coverage": {
            "planned_cases": len(expected),
            "attempted_cases": len(rows),
            "unattempted_cases": len(expected) - len(rows),
            "unique_pages": plan["unique_pages"],
        },
        "runtime": {
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
        },
    }
    artifacts = destination / "runtime-report"
    write(artifacts / "summary.json", summary)
    (artifacts / "report.md").write_text(
        "# Execução do Acessilia\n\n"
        f"Dataset: {plan['dataset']} @ {plan['dataset_revision']}\n\n"
        "Sem métricas de qualidade ou Overall neste perfil.\n\n"
        "Tempos incluem startup do processo, preparação da entrada, cache e serviços; "
        "não medem apenas o modelo nem GPU-hora. Percentis incluem falhas e timeouts. "
        "Páginas na vazão contam ocorrências nas janelas; janelas vizinhas podem "
        "compartilhar páginas. Falhas consomem tempo, mas não contam na vazão de sucesso.\n\n"
        + "```json\n"
        + json.dumps(summary, indent=2, ensure_ascii=False)
        + "\n```\n",
        encoding="utf-8",
    )
    seal(artifacts / "summary.json")
