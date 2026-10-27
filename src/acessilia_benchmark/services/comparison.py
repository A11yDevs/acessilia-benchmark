"""Compare sealed evaluations of identical inputs and evaluator protocols."""

import json
import math

from ..core.runs import load_plan, validate_predictions
from ..io import digest, local_path, read, verify_seal, write


def _load(workspace, name, profile):
    destination, plan = load_plan(workspace, name)
    artifacts = destination / ("runtime-report" if profile == "runtime" else profile)
    verify_seal(artifacts / "summary.json")
    summary = read(artifacts / "summary.json")
    if summary.get("profile") != profile:
        raise ValueError("Perfil do relatório divergente.")
    if profile == "runtime":
        verify_seal(destination / "inference.json")
        evidence = read(destination / "inference.json")
        if summary["inference_sha256"] != digest(destination / "inference.json"):
            raise ValueError("Relatório runtime desatualizado.")
        if summary["plan_sha256"] != digest(destination / "plan.json"):
            raise ValueError("Relatório pertence a outro plano.")
        if evidence.get("system_sha256") != digest(destination / "system.json"):
            raise ValueError("Sistema alterado após inferência.")
        timings = [
            json.loads(line) for line in (destination / "timings.jsonl").read_text().splitlines()
        ]
        if timings != evidence["cases"]:
            raise ValueError("Tempos divergentes da inferência.")
    else:
        validate_predictions(destination, plan)
        verify_seal(artifacts / "execution.json")
        execution = read(artifacts / "execution.json")
        if execution["status"] != "ok" or not execution.get("artifacts_sha256"):
            raise ValueError("Avaliação sem evidência completa; execute uma nova avaliação.")
        for filename, expected in execution["artifacts_sha256"].items():
            if digest(local_path(artifacts, filename)) != expected:
                raise ValueError(f"Artefato de avaliação alterado: {filename}")
        summary["evaluator_runtime"] = execution.get("runtime_versions")
        if execution["predictions_sha256"] != validate_predictions(destination, plan):
            raise ValueError("Avaliação pertence a outras previsões.")
    return plan, summary


def _signature(plan):
    # Paths and run timestamps differ; content and exact case grouping must agree.
    return {
        "dataset": plan["dataset"],
        "revision": plan["dataset_revision"],
        "fixture": plan["fixture"],
        "evaluator": plan["evaluator"],
        "lock": plan["environment_lock_sha256"],
        "cases": sorted(
            (case["id"], case["prediction"], tuple(plan["input_sha256"][p] for p in case["images"]))
            for case in plan["cases"]
        ),
        "references": sorted(plan["reference_sha256"].values()),
    }


def _metrics(summary):
    values = {}

    def walk(node, path, direction):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, (*path, key), direction)
        elif node is None:
            values["/".join(path)] = (None, direction)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
            values["/".join(path)] = (float(node), direction)
        else:
            raise ValueError(f"Métrica inválida: {'/'.join(path)}")

    if summary.get("overall") is not None:
        values["overall"] = (summary["overall"], 1)
    for component, metrics in summary["metrics"].items():
        for metric, value in metrics.items():
            if metric in {"Edit_dist", "TEDS", "CDM"}:
                walk(value, (component, metric), -1 if metric == "Edit_dist" else 1)
    return values


def compare(workspace, base, candidate, profile="full", tolerance=0.0, output=None):
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Tolerância deve ser finita e >= 0.")
    left_plan, left = _load(workspace, base, profile)
    right_plan, right = _load(workspace, candidate, profile)
    if _signature(left_plan) != _signature(right_plan):
        raise ValueError(
            "Rodadas incompatíveis: dataset, amostra, referências ou avaliador diferem."
        )
    result = {
        "base": base,
        "candidate": candidate,
        "profile": profile,
        "fixture": left_plan["fixture"],
        "tolerance": tolerance,
        "leaderboard_comparable": False,
        "quality_regressions": [],
        "metrics": {},
        "runtime": {"base": left.get("runtime"), "candidate": right.get("runtime")},
        "runtime_deltas": {},
        "systems": {"base": left.get("system"), "candidate": right.get("system")},
        "prediction_origins": {
            "base": left.get("prediction_origin"),
            "candidate": right.get("prediction_origin"),
        },
        "processing": {
            "base": left.get("processing", {"status": "unknown"}),
            "candidate": right.get("processing", {"status": "unknown"}),
        },
    }
    for key in (
        "total_seconds",
        "p50_seconds_per_window",
        "p95_seconds_per_window",
        "failures",
        "timeouts",
        "inference_calls",
        "failed_calls",
        "success_rate",
        "successful_pages_per_minute",
        "processed_pages_per_minute",
    ):
        before = (left.get("runtime") or {}).get(key)
        after = (right.get("runtime") or {}).get(key)
        if before is not None and after is not None:
            result["runtime_deltas"][key] = after - before
    if profile != "runtime":
        if left["coverage"] != right["coverage"]:
            raise ValueError("Cobertura pontuada difere; comparação de qualidade recusada.")
        if left["overall_details"]["protocol"] != right["overall_details"]["protocol"]:
            raise ValueError("Protocolos Overall diferentes.")
        if left.get("evaluator_runtime") != right.get("evaluator_runtime"):
            raise ValueError("Versões do ambiente de avaliação diferentes.")
        left_cases = left["overall_details"].get("case_scores", {})
        right_cases = right["overall_details"].get("case_scores", {})
        if {k: sorted(v["components"]) for k, v in left_cases.items()} != {
            k: sorted(v["components"]) for k, v in right_cases.items()
        }:
            raise ValueError("Cobertura de componentes por caso difere.")
        a, b = _metrics(left), _metrics(right)
        if not any(value is not None for value, _ in a.values()):
            raise ValueError("Nenhuma métrica finita para comparar.")
        if a.keys() != b.keys():
            raise ValueError("Componentes de métricas diferentes; não omita métricas ausentes.")
        for key, (before, direction) in a.items():
            after = b[key][0]
            if (before is None) != (after is None):
                raise ValueError(f"Métrica perdeu/ganhou cobertura: {key}")
            delta = None if before is None else after - before
            # Overall is in percentage points; official component metrics are fractions.
            gain = None if delta is None else delta * direction * (1 if key == "overall" else 100)
            result["metrics"][key] = {
                "base": before,
                "candidate": after,
                "delta": delta,
                "gain_points": gain,
            }
            if gain is not None and gain < -tolerance:
                result["quality_regressions"].append(key)
        result["verdict"] = "regressed" if result["quality_regressions"] else "no_regression"
        result["processing_review"] = any(
            item.get("status") in {"reported_warnings", "unknown", "not_available"}
            for item in result["processing"].values()
        )
        result["scope"] = "Mesma amostra local; não é aceite tune/holdout nem ranking oficial."
    else:
        result["verdict"] = "runtime_only"
        result["scope"] = "Inclui tentativas, falhas e retomadas; não avalia qualidade."
    if output:
        output = output.expanduser().absolute()
        if output.exists() or output.resolve().is_relative_to(workspace.root / "runs"):
            raise ValueError("Escolha um arquivo novo fora de runs/ para preservar as evidências.")
        write(output, result)
    return result
