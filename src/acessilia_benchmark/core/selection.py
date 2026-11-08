"""Validation and application of the fixed, difficulty-balanced OmniDocBench sample."""

import hashlib
import math
from collections import Counter
from pathlib import Path

from ..io import digest, read

POLICY = "omnidocbench-80-difficulty-diverse-v3"
SAMPLE_SIZE = 80
PUBLIC_ORDER = ("texto_comum", "ocr_dificil", "tabelas", "formulas", "layout_complexo")
DIFFICULTY_QUOTAS = {"facil": 4, "medio": 6, "dificil": 6}
CATEGORY_SIZE = sum(DIFFICULTY_QUOTAS.values())
DIMENSIONS = ("source", "language", "layout", "source_language")
SELECTION_FILENAME = "selection.json"


def _count_map(value, field):
    if (
        not isinstance(value, dict)
        or not value
        or list(value) != sorted(value)
        or not all(
            isinstance(key, str)
            and key
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
            for key, count in value.items()
        )
    ):
        raise ValueError(f"Manifesto de seleção inválido: {field}.")
    return value


def _total_variation(sample, population, sample_size, population_size):
    keys = set(sample) | set(population)
    return 0.5 * sum(
        abs(sample.get(key, 0) / sample_size - population.get(key, 0) / population_size)
        for key in keys
    )


def _row_is_eligible(category, row):
    if category == "ocr_dificil":
        return row["text_blocks"] > 0 and any(
            row[field]
            for field in ("fuzzy_scan", "handwritten_note", "rotated_text", "colorful_background")
        )
    if category == "tabelas":
        return row["tables"] > 0
    if category == "formulas":
        return row["display_formulas"] > 0 or row["inline_formulas"] > 0
    if category == "layout_complexo":
        return row["layout"] != "single_column" or (
            row["captions"] > 0 and row["block_count"] >= 10
        )
    if category == "texto_comum":
        return (
            row["text_blocks"] >= 2
            and not row["fuzzy_scan"]
            and not row["handwritten_note"]
            and row["tables"] == 0
            and row["display_formulas"] == 0
        )
    return False


def validate_manifest(
    manifest,
    dataset,
    revision,
    annotation_sha256,
    cases=None,
    original_records=None,
):
    """Validate selection metadata and bind every row to its original JSON record."""
    if dataset != "omnidocbench":
        raise ValueError("Este arquivo de seleção é exclusivo do OmniDocBench.")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 3:
        raise ValueError("Manifesto de seleção inválido: schema_version.")
    expected = {
        "selection_policy": POLICY,
        "dataset": "omnidocbench",
        "dataset_revision": revision,
        "annotation_sha256": annotation_sha256,
        "seed": 42,
        "count": SAMPLE_SIZE,
        "category_order": list(PUBLIC_ORDER),
        "difficulty_quotas": DIFFICULTY_QUOTAS,
        "category_quotas": dict.fromkeys(PUBLIC_ORDER, CATEGORY_SIZE),
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"Manifesto de seleção incompatível: {field}.")

    population_size = manifest.get("population_size")
    if (
        isinstance(population_size, bool)
        or not isinstance(population_size, int)
        or population_size < SAMPLE_SIZE
    ):
        raise ValueError("Manifesto de seleção inválido: população total.")
    population = {
        dimension: _count_map(manifest.get(f"population_by_{dimension}"), f"população {dimension}")
        for dimension in DIMENSIONS
    }
    sample = {
        dimension: _count_map(manifest.get(f"sample_by_{dimension}"), f"amostra {dimension}")
        for dimension in DIMENSIONS
    }
    if any(sum(values.values()) != population_size for values in population.values()):
        raise ValueError("Manifesto de seleção inválido: distribuição populacional.")
    if any(sum(values.values()) != SAMPLE_SIZE for values in sample.values()):
        raise ValueError("Manifesto de seleção inválido: distribuição da amostra.")

    eligible = manifest.get("eligible_candidates_by_category")
    if (
        not isinstance(eligible, dict)
        or list(eligible) != list(PUBLIC_ORDER)
        or any(
            isinstance(eligible.get(category), bool)
            or not isinstance(eligible.get(category), int)
            or eligible[category] < CATEGORY_SIZE
            for category in PUBLIC_ORDER
        )
    ):
        raise ValueError("Manifesto de seleção inválido: candidatos elegíveis.")

    categories = manifest.get("categories")
    if not isinstance(categories, dict) or list(categories) != list(PUBLIC_ORDER):
        raise ValueError("Manifesto de seleção inválido: categorias de desafio.")
    difficulty_counts = manifest.get("difficulty_counts")
    expected_difficulty_counts = {category: DIFFICULTY_QUOTAS for category in PUBLIC_ORDER}
    if difficulty_counts != expected_difficulty_counts:
        raise ValueError("Manifesto de seleção inválido: cotas de dificuldade.")

    representativeness = manifest.get("representativeness")
    if (
        not isinstance(representativeness, dict)
        or representativeness.get("method") != "marginal_total_variation_distance"
    ):
        raise ValueError("Manifesto de seleção inválido: diagnóstico de representatividade.")
    declared_tv = representativeness.get("dimensions")
    if not isinstance(declared_tv, dict) or set(declared_tv) != set(DIMENSIONS):
        raise ValueError("Manifesto de seleção inválido: dimensões de representatividade.")
    for dimension in DIMENSIONS:
        value = declared_tv[dimension]
        actual = _total_variation(
            sample[dimension], population[dimension], SAMPLE_SIZE, population_size
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not math.isclose(value, actual, rel_tol=1e-12, abs_tol=1e-12)
        ):
            raise ValueError(f"Manifesto de seleção inválido: TV de {dimension} divergente.")

    rows_by_id = {}
    flattened = []
    seen_indices = set()
    seen_paths = set()
    calculated_difficulty = {}
    calculated_sample = {dimension: Counter() for dimension in DIMENSIONS}
    for category in PUBLIC_ORDER:
        rows = categories[category]
        if not isinstance(rows, list) or len(rows) != CATEGORY_SIZE:
            raise ValueError(f"Manifesto de seleção inválido: cota de {category}.")
        levels = Counter()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Manifesto de seleção inválido: item em {category}.")
            case_id = row.get("id")
            image = row.get("image")
            original_path = row.get("original_image_path")
            record_index = row.get("original_record_index")
            if (
                not isinstance(case_id, str)
                or not case_id
                or Path(case_id).name != case_id
                or not isinstance(image, str)
                or Path(image).name != image
                or Path(image).stem != case_id
                or not isinstance(original_path, str)
                or not original_path
                or Path(original_path).name != image
                or isinstance(record_index, bool)
                or not isinstance(record_index, int)
                or not 0 <= record_index < population_size
            ):
                raise ValueError(f"Manifesto de seleção inválido: identidade em {category}.")
            if case_id in rows_by_id:
                raise ValueError(f"Manifesto de seleção contém ID duplicado: {case_id}.")
            if record_index in seen_indices:
                raise ValueError(f"Índice original repetido na seleção: {record_index}.")
            if original_path in seen_paths:
                raise ValueError(f"Caminho original repetido na seleção: {original_path}.")

            level = row.get("difficulty_band")
            score = row.get("difficulty_score")
            if (
                level not in DIFFICULTY_QUOTAS
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise ValueError(f"Manifesto de seleção inválido: dificuldade em {case_id}.")
            levels[level] += 1

            for field in ("data_source", "language", "layout"):
                if not isinstance(row.get(field), str) or not row[field]:
                    raise ValueError(f"Manifesto de seleção inválido: {field} em {case_id}.")
            if row["layout"] not in population["layout"]:
                raise ValueError(f"Layout desconhecido em {case_id}.")
            document_group = row.get("document_group")
            if document_group is not None and not isinstance(document_group, str):
                raise ValueError(f"Manifesto de seleção inválido: document_group em {case_id}.")
            if row.get("page_no") is not None and not isinstance(row["page_no"], (int, str)):
                raise ValueError(f"Manifesto de seleção inválido: page_no em {case_id}.")

            for field in (
                "fuzzy_scan",
                "handwritten_note",
                "rotated_text",
                "colorful_background",
                "watermark",
            ):
                if not isinstance(row.get(field), bool):
                    raise ValueError(f"Manifesto de seleção inválido: {field} em {case_id}.")
            for field in (
                "tables",
                "display_formulas",
                "inline_formulas",
                "text_blocks",
                "block_count",
                "captions",
                "reading_order_blocks",
            ):
                value = row.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"Manifesto de seleção inválido: {field} em {case_id}.")
            if not isinstance(row.get("special_issue"), list) or not all(
                isinstance(issue, str) for issue in row["special_issue"]
            ):
                raise ValueError(f"Manifesto de seleção inválido: special_issue em {case_id}.")
            if not isinstance(row.get("subset"), str):
                raise ValueError(f"Manifesto de seleção inválido: subset em {case_id}.")
            if not isinstance(row.get("features"), list) or not all(
                isinstance(feature, str) for feature in row["features"]
            ):
                raise ValueError(f"Manifesto de seleção inválido: features em {case_id}.")
            if not _row_is_eligible(category, row):
                raise ValueError(f"Página não elegível para {category}: {case_id}.")

            calculated_sample["source"][row["data_source"]] += 1
            calculated_sample["language"][row["language"]] += 1
            calculated_sample["layout"][row["layout"]] += 1
            calculated_sample["source_language"][f"{row['data_source']}|{row['language']}"] += 1
            flattened.append(case_id)
            rows_by_id[case_id] = (category, row)
            seen_indices.add(record_index)
            seen_paths.add(original_path)
        if dict(levels) != DIFFICULTY_QUOTAS:
            raise ValueError(f"Cotas de dificuldade divergentes em {category}.")
        calculated_difficulty[category] = dict(levels)

    if calculated_difficulty != difficulty_counts:
        raise ValueError("Contagens de dificuldade divergem das páginas selecionadas.")
    for dimension in DIMENSIONS:
        if dict(sorted(calculated_sample[dimension].items())) != sample[dimension]:
            raise ValueError(f"Distribuição amostral de {dimension} divergente.")

    if flattened != manifest.get("case_ids") or len(flattened) != SAMPLE_SIZE:
        raise ValueError("IDs do manifesto não correspondem às categorias.")
    selection_sha256 = hashlib.sha256("\n".join(flattened).encode("utf-8")).hexdigest()
    if manifest.get("selection_sha256") != selection_sha256:
        raise ValueError("SHA-256 dos IDs do manifesto de seleção diverge.")

    if original_records is not None:
        if not isinstance(original_records, list) or len(original_records) != population_size:
            raise ValueError("Anotações originais incompatíveis com a população do manifesto.")
        actual_population = {dimension: Counter() for dimension in DIMENSIONS}
        for record in original_records:
            attrs = record.get("page_info", {}).get("page_attribute") or {}
            actual_population["source"][str(attrs.get("data_source", "unknown"))] += 1
            actual_population["language"][str(attrs.get("language", "unknown"))] += 1
            actual_population["layout"][str(attrs.get("layout", "unknown"))] += 1
            actual_population["source_language"][
                f"{attrs.get('data_source', 'unknown')}|{attrs.get('language', 'unknown')}"
            ] += 1
        for dimension in DIMENSIONS:
            if dict(sorted(actual_population[dimension].items())) != population[dimension]:
                raise ValueError(
                    f"Distribuição de {dimension} não corresponde às anotações originais."
                )
        for _category, row in rows_by_id.values():
            original = original_records[row["original_record_index"]]
            info = original.get("page_info", {})
            attrs = info.get("page_attribute") or {}
            special = attrs.get("special_issue") or []
            if not isinstance(special, list):
                special = [special]
            if (
                info.get("image_path") != row["original_image_path"]
                or Path(str(info.get("image_path", ""))).stem != row["id"]
                or info.get("page_no") != row.get("page_no")
                or str(attrs.get("data_source", "unknown")) != row["data_source"]
                or str(attrs.get("language", "unknown")) != row["language"]
                or str(attrs.get("layout", "unknown")) != row["layout"]
                or special != row["special_issue"]
                or str(attrs.get("subset", "unknown")) != row["subset"]
            ):
                raise ValueError(f"Mapeamento ao registro original diverge: {row['id']}.")

    if cases is not None:
        cases_by_id = {case["id"]: case for case in cases}
        if len(cases_by_id) != len(cases) or not set(rows_by_id).issubset(cases_by_id):
            raise ValueError("Manifesto de seleção não corresponde aos casos disponíveis.")
        for case_id, (_category, row) in rows_by_id.items():
            case = cases_by_id[case_id]
            if len(case.get("images", [])) != 1 or Path(case["images"][0]).name != row["image"]:
                raise ValueError(f"Imagem do manifesto diverge do caso {case_id}.")

    return rows_by_id


def case_selection(category, row):
    """Return immutable per-page challenge and original-record metadata for reports."""
    return {
        "category": category,
        "difficulty_band": row["difficulty_band"],
        "difficulty_score": row["difficulty_score"],
        "data_source": row["data_source"],
        "language": row["language"],
        "layout": row["layout"],
        "original_record_index": row["original_record_index"],
        "original_image_path": row["original_image_path"],
        "page_no": row["page_no"],
        "document_group": row["document_group"],
        "special_issue": row["special_issue"],
        "features": row["features"],
        "fuzzy_scan": row["fuzzy_scan"],
        "handwritten_note": row["handwritten_note"],
        "rotated_text": row["rotated_text"],
        "colorful_background": row["colorful_background"],
        "watermark": row["watermark"],
        "tables": row["tables"],
        "display_formulas": row["display_formulas"],
        "inline_formulas": row["inline_formulas"],
        "text_blocks": row["text_blocks"],
        "block_count": row["block_count"],
        "captions": row["captions"],
        "reading_order_blocks": row["reading_order_blocks"],
    }


def manifest_identity(manifest, path):
    """Keep compact selection provenance while hashing the full copied manifest."""
    return {
        "policy": manifest["selection_policy"],
        "manifest": SELECTION_FILENAME,
        "manifest_sha256": digest(path),
        "selection_sha256": manifest["selection_sha256"],
        "annotation_sha256": manifest["annotation_sha256"],
        "seed": manifest["seed"],
        "category_order": list(manifest["category_order"]),
        "category_counts": {
            name: len(manifest["categories"][name]) for name in manifest["category_order"]
        },
        "eligible_candidates_by_category": manifest["eligible_candidates_by_category"],
        "category_quotas": manifest["category_quotas"],
        "difficulty_quotas": manifest["difficulty_quotas"],
        "difficulty_counts": manifest["difficulty_counts"],
        "population_size": manifest["population_size"],
        "population_by_source": manifest["population_by_source"],
        "sample_by_source": manifest["sample_by_source"],
        "population_by_language": manifest["population_by_language"],
        "sample_by_language": manifest["sample_by_language"],
        "population_by_source_language": manifest["population_by_source_language"],
        "sample_by_source_language": manifest["sample_by_source_language"],
        "population_by_layout": manifest["population_by_layout"],
        "sample_by_layout": manifest["sample_by_layout"],
        "representativeness": manifest["representativeness"],
    }


def validate_run_selection(destination, plan):
    """Bind the copied selection, original annotations, and case labels to a plan."""
    selection = plan.get("selection")
    if selection is None:
        if (destination / SELECTION_FILENAME).exists() or any(
            "selection_group" in case for case in plan["cases"]
        ):
            raise ValueError("Plano contém artefatos de seleção sem proveniência.")
        return
    path = destination / SELECTION_FILENAME
    if not path.is_file() or digest(path) != selection.get("manifest_sha256"):
        raise ValueError("Manifesto de seleção ausente ou alterado.")
    snapshot = Path(plan["snapshot"])
    annotations = snapshot / "OmniDocBench.json"
    if not annotations.is_file() or digest(annotations) != selection.get("annotation_sha256"):
        raise ValueError("Anotações do manifesto de seleção ausentes ou alteradas.")
    manifest = read(path)
    original_records = read(annotations)
    rows_by_id = validate_manifest(
        manifest,
        plan["dataset"],
        plan["dataset_revision"],
        selection["annotation_sha256"],
        original_records=original_records,
    )
    if manifest_identity(manifest, path) != selection:
        raise ValueError("Identidade do manifesto diverge do plano.")
    case_ids = [case["id"] for case in plan["cases"]]
    if case_ids != manifest["case_ids"]:
        raise ValueError("Casos da rodada divergem da ordem do manifesto.")
    for case in plan["cases"]:
        category, row = rows_by_id[case["id"]]
        if case.get("selection_group") != case_selection(category, row):
            raise ValueError(f"Metadados de seleção divergentes: {case['id']}.")
