#!/usr/bin/env python3
"""Select a reproducible, disjoint difficulty-balanced OmniDocBench sample."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
SEED = 42
SAMPLE_SIZE = 80
CATEGORIES = ("ocr_dificil", "formulas", "texto_comum", "tabelas", "layout_complexo")
PUBLIC_ORDER = ("texto_comum", "ocr_dificil", "tabelas", "formulas", "layout_complexo")
DIFFICULTY_QUOTAS = {"facil": 4, "medio": 6, "dificil": 6}
CATEGORY_QUOTA = sum(DIFFICULTY_QUOTAS.values())
POLICY = "omnidocbench-80-difficulty-diverse-v3"
SOURCE_LANGUAGE_WEIGHT = 0.3
UNSEEN_SOURCE_LANGUAGE_BONUS = 0.1


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256(f"{SEED}|{value}".encode()).hexdigest()


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "sim"}


def bucket(value: int, lower: int, upper: int) -> str:
    return "0" if value <= lower else "1" if value <= upper else "2"


def text_attr(block: dict, field: str, default: str = "unknown") -> str:
    attributes = block.get("attribute") or {}
    if not isinstance(attributes, dict):
        return default
    return str(attributes.get(field, default))


def document_group(image: str) -> str | None:
    stem = Path(image).stem
    if re.fullmatch(r"page-[0-9a-f-]{36}", stem, flags=re.IGNORECASE):
        return None
    match = re.fullmatch(r"(.+?)(?:_page)?_\d+", stem)
    return match.group(1) if match else None


@dataclass(frozen=True)
class Page:
    id: str
    image: str
    original_image_path: str
    original_record_index: int
    page_no: int | str | None
    document_group: str | None
    source: str
    language: str
    layout: str
    special_issue: tuple[str, ...]
    subset: str
    scan: bool
    note: bool
    colored: bool
    watermark: bool
    rotated: bool
    n_text: int
    n_blocks: int
    n_chars: int
    n_tables: int
    table_lines: tuple[str, ...]
    table_span: bool
    table_equation: bool
    table_vertical: bool
    table_background: bool
    n_display: int
    n_inline: int
    math_length: int
    math_complexity: int
    n_figures: int
    n_captions: int
    n_footnotes: int
    reading_orders: int

    def eligible(self, category: str) -> bool:
        if category == "ocr_dificil":
            return self.n_text > 0 and (self.scan or self.note or self.rotated or self.colored)
        if category == "tabelas":
            return self.n_tables > 0
        if category == "formulas":
            return self.n_display > 0 or self.n_inline > 0
        if category == "layout_complexo":
            return self.layout != "single_column" or (self.n_captions > 0 and self.n_blocks >= 10)
        if category == "texto_comum":
            return (
                self.n_text >= 2
                and not self.scan
                and not self.note
                and self.n_tables == 0
                and self.n_display == 0
            )
        raise ValueError(category)

    def difficulty(self, category: str) -> float:
        if category == "texto_comum":
            return (
                math.log1p(self.n_chars) * 0.55
                + math.log1p(self.n_text) * 0.7
                + 1.4 * (self.layout != "single_column")
                + 0.7 * self.n_footnotes
                + 0.5 * self.rotated
            )
        if category == "ocr_dificil":
            return (
                3.0 * self.scan
                + 3.0 * self.note
                + 2.0 * self.rotated
                + 1.5 * self.colored
                + 0.6 * self.watermark
                + 0.4 * math.log1p(self.n_chars)
                + 0.4 * (self.language == "en_ch_mixed")
            )
        if category == "tabelas":
            return (
                3.0 * self.table_span
                + 3.0 * self.table_vertical
                + 2.0 * self.table_equation
                + 1.0 * self.table_background
                + 2.0 * any(line in {"wireless_line", "less_line"} for line in self.table_lines)
                + math.log1p(self.n_tables)
                + 0.4 * math.log1p(self.n_text)
            )
        if category == "formulas":
            return (
                1.2 * math.log1p(self.n_display)
                + 0.8 * math.log1p(self.n_inline)
                + 0.45 * math.log1p(self.math_length)
                + 0.5 * self.math_complexity
                + 0.4 * (self.layout != "single_column")
            )
        if category == "layout_complexo":
            layout_weight = {
                "single_column": 0,
                "double_column": 1.5,
                "1andmore_column": 3,
                "three_column": 3.5,
                "other_layout": 3.5,
            }
            return (
                layout_weight.get(self.layout, 1.5)
                + 0.5 * math.log1p(self.n_blocks)
                + 0.6 * self.n_captions
                + 0.3 * self.n_figures
                + 0.5 * self.n_footnotes
                + 0.3 * math.log1p(self.reading_orders)
            )
        raise ValueError(category)

    def features(self, category: str) -> tuple[str, ...]:
        common = [
            f"origem:{self.source}",
            f"idioma:{self.language}",
            f"layout:{self.layout}",
            f"densidade:{bucket(self.n_blocks, 6, 16)}",
        ]
        if category == "texto_comum":
            extra = [
                f"tamanho_texto:{bucket(self.n_chars, 800, 2400)}",
                f"blocos_texto:{bucket(self.n_text, 4, 12)}",
                f"rodape:{self.n_footnotes > 0}",
                f"figuras:{self.n_figures > 0}",
            ]
        elif category == "ocr_dificil":
            extra = [
                f"blur:{self.scan}",
                f"nota:{self.note}",
                f"girado:{self.rotated}",
                f"colorido:{self.colored}",
                f"watermark:{self.watermark}",
                f"tamanho_texto:{bucket(self.n_chars, 500, 1800)}",
            ]
        elif category == "tabelas":
            extra = [f"borda:{line}" for line in self.table_lines]
            extra += [
                f"mesclagem:{self.table_span}",
                f"vertical:{self.table_vertical}",
                f"formula_tabela:{self.table_equation}",
                f"fundo_tabela:{self.table_background}",
                f"qtd_tabelas:{bucket(self.n_tables, 1, 2)}",
            ]
        elif category == "formulas":
            extra = [
                f"display:{bucket(self.n_display, 0, 3)}",
                f"inline:{bucket(self.n_inline, 0, 3)}",
                f"latex_tamanho:{bucket(self.math_length, 100, 550)}",
                f"latex_complexidade:{bucket(self.math_complexity, 0, 3)}",
            ]
        else:
            extra = [
                f"qtd_bloco:{bucket(self.n_blocks, 10, 25)}",
                f"figuras:{self.n_figures > 0}",
                f"legendas:{self.n_captions > 0}",
                f"cabecalho_rodape:{self.n_footnotes > 0}",
                f"tabela:{self.n_tables > 0}",
            ]
        return tuple(sorted(set(common + extra)))


def extract_page(raw: dict, record_index: int) -> Page:
    info = raw["page_info"]
    attributes = info.get("page_attribute") or {}
    original_image_path = str(info["image_path"])
    image = Path(original_image_path).name
    special = attributes.get("special_issue") or []
    special_issue = (
        tuple(str(item) for item in special) if isinstance(special, list) else (str(special),)
    )
    special_flags = set(special_issue)
    blocks = [
        block for block in raw.get("layout_dets", []) if not truthy(block.get("ignore", False))
    ]
    tally = collections.Counter(block.get("category_type", "unknown") for block in blocks)
    tables = [block for block in blocks if block.get("category_type") == "table"]
    formulas = [block for block in blocks if block.get("category_type") == "equation_isolated"]
    text_blocks = [
        block
        for block in blocks
        if block.get("category_type")
        in {"text_block", "title", "header", "footer", "page_footnote", "reference", "code_txt"}
    ]
    inline_count = 0
    rotated = False
    all_math = []
    for block in blocks:
        rotated |= text_attr(block, "text_rotate", "normal") not in {"normal", "unknown"}
        for span in block.get("line_with_spans") or []:
            if span.get("category_type") == "equation_inline" and not truthy(
                span.get("ignore", False)
            ):
                inline_count += 1
                all_math.append(str(span.get("latex") or span.get("text") or ""))
    all_math.extend(str(block.get("latex") or "") for block in formulas)
    latex = "\n".join(all_math)
    math_complexity = sum(
        latex.count(marker)
        for marker in ("\\frac", "\\sqrt", "\\sum", "\\int", "\\begin", "\\left", "\\matrix")
    )
    data_source = str(attributes.get("data_source", "unknown"))
    return Page(
        id=Path(image).stem,
        image=image,
        original_image_path=original_image_path,
        original_record_index=record_index,
        page_no=info.get("page_no"),
        document_group=document_group(image),
        source=data_source,
        language=str(attributes.get("language", "unknown")),
        layout=str(attributes.get("layout", "unknown")),
        special_issue=special_issue,
        subset=str(attributes.get("subset", "unknown")),
        scan=truthy(attributes.get("fuzzy_scan"))
        or bool(special_flags & {"fuzzy_scan", "fuzzy_content"}),
        note=data_source == "note" or "handwriting" in special_flags,
        colored=truthy(attributes.get("colorful_backgroud", attributes.get("colorful_background")))
        or bool(special_flags & {"colorful_backgroud", "colorful_background"}),
        watermark=truthy(attributes.get("watermark")),
        rotated=rotated,
        n_text=tally["text_block"],
        n_blocks=len(blocks),
        n_chars=sum(len(str(block.get("text") or "")) for block in text_blocks),
        n_tables=len(tables),
        table_lines=tuple(sorted({text_attr(table, "line") for table in tables})),
        table_span=any(truthy(text_attr(table, "with_span")) for table in tables),
        table_equation=any(truthy(text_attr(table, "include_equation")) for table in tables),
        table_vertical=any(truthy(text_attr(table, "table_vertical")) for table in tables),
        table_background=any(truthy(text_attr(table, "include_backgroud")) for table in tables),
        n_display=len(formulas),
        n_inline=inline_count,
        math_length=len(latex),
        math_complexity=math_complexity,
        n_figures=tally["figure"],
        n_captions=tally["figure_caption"] + tally["table_caption"] + tally["equation_caption"],
        n_footnotes=tally["page_footnote"] + tally["table_footnote"] + tally["figure_footnote"],
        reading_orders=sum(block.get("order") is not None for block in blocks),
    )


def _marginal_score(candidate: Page, counts: dict, population: dict, population_size: int) -> float:
    score = 0.0
    labels = {
        "source": candidate.source,
        "language": candidate.language,
        "layout": candidate.layout,
        "source_language": f"{candidate.source}|{candidate.language}",
    }
    for dimension, label in labels.items():
        target = SAMPLE_SIZE * population[dimension][label] / population_size
        current = counts[dimension][label]
        weight = SOURCE_LANGUAGE_WEIGHT if dimension == "source_language" else 1.0
        score += weight * (2 * (current - target) + 1) / (target + 1)
        if current == 0:
            score -= weight
            if dimension == "source_language":
                score -= UNSEEN_SOURCE_LANGUAGE_BONUS
    return score


def choose(pages: list[Page]):
    if len({page.id for page in pages}) != len(pages):
        raise ValueError("IDs de imagens repetidos: verifique o snapshot.")
    population = {
        "source": collections.Counter(page.source for page in pages),
        "language": collections.Counter(page.language for page in pages),
        "layout": collections.Counter(page.layout for page in pages),
        "source_language": collections.Counter(f"{page.source}|{page.language}" for page in pages),
    }
    counts = {dimension: collections.Counter() for dimension in population}
    selected_ids: set[str] = set()
    result = {}
    for category in CATEGORIES:
        pool = [page for page in pages if page.id not in selected_ids and page.eligible(category)]
        if len(pool) < SAMPLE_SIZE // len(PUBLIC_ORDER):
            raise ValueError(f"Candidatos insuficientes para {category}.")
        pool.sort(
            key=lambda page: (page.difficulty(category), stable_hash(f"{category}|{page.id}"))
        )
        easy_end = min(len(pool) - 12, max(4, len(pool) // 3))
        medium_end = easy_end + min(len(pool) - easy_end - 6, max(6, len(pool) // 3))
        bands = {
            "facil": pool[:easy_end],
            "medio": pool[easy_end:medium_end],
            "dificil": pool[medium_end:],
        }
        if any(len(bands[level]) < quota for level, quota in DIFFICULTY_QUOTAS.items()):
            raise ValueError(f"Faixas de dificuldade insuficientes para {category}.")
        feature_frequency = collections.Counter(
            feature for page in pool for feature in page.features(category)
        )
        feature_counts: collections.Counter[str] = collections.Counter()
        group = []
        while len(group) < CATEGORY_QUOTA:
            for level, quota in DIFFICULTY_QUOTAS.items():
                if sum(item[1] == level for item in group) >= quota:
                    continue
                candidates = [page for page in bands[level] if page.id not in selected_ids]
                if not candidates:
                    raise ValueError(f"Sem páginas distintas para {category}/{level}.")

                def quality(
                    page: Page,
                    category: str = category,
                    level: str = level,
                    feature_frequency: collections.Counter = feature_frequency,
                    feature_counts: collections.Counter = feature_counts,
                ) -> tuple[float, str]:
                    global_score = _marginal_score(page, counts, population, len(pages))
                    diversity = 0.0
                    for feature in page.features(category):
                        name = feature.split(":", 1)[0]
                        importance = (
                            3.0
                            if name
                            in {
                                "origem",
                                "idioma",
                                "layout",
                                "borda",
                                "mesclagem",
                                "vertical",
                                "blur",
                                "nota",
                                "girado",
                                "display",
                                "inline",
                                "formula_tabela",
                            }
                            else 1.5
                        )
                        rarity = min(
                            2.5, math.sqrt(SAMPLE_SIZE / max(feature_frequency[feature], 1))
                        )
                        diversity += importance * rarity / (1 + feature_counts[feature])
                    return global_score - 0.05 * diversity, stable_hash(
                        f"{category}|{level}|{page.id}"
                    )

                winner = min(candidates, key=quality)
                score = round(winner.difficulty(category), 4)
                group.append((winner, level, score))
                selected_ids.add(winner.id)
                counts["source"][winner.source] += 1
                counts["language"][winner.language] += 1
                counts["layout"][winner.layout] += 1
                counts["source_language"][f"{winner.source}|{winner.language}"] += 1
                feature_counts.update(winner.features(category))
        result[category] = group
    if len(selected_ids) != SAMPLE_SIZE:
        raise AssertionError("A seleção deve conter exatamente 80 páginas distintas.")
    return result, population


def _total_variation(
    sample: dict[str, int], population: dict[str, int], sample_size: int, population_size: int
) -> float:
    keys = sorted(set(sample) | set(population))
    return 0.5 * sum(
        abs(sample.get(key, 0) / sample_size - population.get(key, 0) / population_size)
        for key in keys
    )


def build_manifest(pages: list[Page], annotation_sha256: str) -> dict:
    selection, population = choose(pages)
    categories = {}
    for category in PUBLIC_ORDER:
        categories[category] = []
        for page, level, score in selection[category]:
            categories[category].append(
                {
                    "id": page.id,
                    "image": page.image,
                    "original_record_index": page.original_record_index,
                    "original_image_path": page.original_image_path,
                    "page_no": page.page_no,
                    "document_group": page.document_group,
                    "difficulty_band": level,
                    "difficulty_score": score,
                    "data_source": page.source,
                    "language": page.language,
                    "layout": page.layout,
                    "special_issue": list(page.special_issue),
                    "subset": page.subset,
                    "fuzzy_scan": page.scan,
                    "handwritten_note": page.note,
                    "rotated_text": page.rotated,
                    "colorful_background": page.colored,
                    "watermark": page.watermark,
                    "tables": page.n_tables,
                    "display_formulas": page.n_display,
                    "inline_formulas": page.n_inline,
                    "text_blocks": page.n_text,
                    "block_count": page.n_blocks,
                    "captions": page.n_captions,
                    "reading_order_blocks": page.reading_orders,
                    "features": list(page.features(category)),
                }
            )
    case_ids = [row["id"] for category in PUBLIC_ORDER for row in categories[category]]
    sample = {
        "source": dict(
            sorted(
                collections.Counter(
                    row["data_source"] for rows in categories.values() for row in rows
                ).items()
            )
        ),
        "language": dict(
            sorted(
                collections.Counter(
                    row["language"] for rows in categories.values() for row in rows
                ).items()
            )
        ),
        "layout": dict(
            sorted(
                collections.Counter(
                    row["layout"] for rows in categories.values() for row in rows
                ).items()
            )
        ),
        "source_language": dict(
            sorted(
                collections.Counter(
                    f"{row['data_source']}|{row['language']}"
                    for rows in categories.values()
                    for row in rows
                ).items()
            )
        ),
    }
    population_sorted = {
        dimension: dict(sorted(values.items())) for dimension, values in population.items()
    }
    total_variation = {
        dimension: _total_variation(
            sample[dimension], population_sorted[dimension], SAMPLE_SIZE, len(pages)
        )
        for dimension in population
    }
    eligible_counts = {
        category: sum(page.eligible(category) for page in pages) for category in PUBLIC_ORDER
    }
    difficulty_counts = {
        category: dict(collections.Counter(row["difficulty_band"] for row in rows))
        for category, rows in categories.items()
    }
    return {
        "schema_version": 3,
        "selection_policy": POLICY,
        "dataset": "omnidocbench",
        "dataset_revision": REVISION,
        "annotation_sha256": annotation_sha256,
        "seed": SEED,
        "population_size": len(pages),
        "population_by_source": population_sorted["source"],
        "sample_by_source": sample["source"],
        "population_by_language": population_sorted["language"],
        "sample_by_language": sample["language"],
        "population_by_source_language": population_sorted["source_language"],
        "sample_by_source_language": sample["source_language"],
        "population_by_layout": population_sorted["layout"],
        "sample_by_layout": sample["layout"],
        "eligible_candidates_by_category": eligible_counts,
        "difficulty_quotas": DIFFICULTY_QUOTAS,
        "category_quotas": {category: CATEGORY_QUOTA for category in PUBLIC_ORDER},
        "difficulty_counts": difficulty_counts,
        "representativeness": {
            "method": "marginal_total_variation_distance",
            "dimensions": total_variation,
        },
        "count": len(case_ids),
        "selection_sha256": hashlib.sha256("\n".join(case_ids).encode("utf-8")).hexdigest(),
        "category_order": list(PUBLIC_ORDER),
        "case_ids": case_ids,
        "categories": categories,
    }


def _mapping_csv(manifest: dict) -> str:
    fields = (
        "selection_order",
        "challenge_category",
        "difficulty_band",
        "difficulty_score",
        "id",
        "original_record_index",
        "original_image_path",
        "page_no",
        "data_source",
        "language",
        "layout",
        "document_group",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    order = 0
    for category in manifest["category_order"]:
        for row in manifest["categories"][category]:
            order += 1
            writer.writerow(
                {
                    "selection_order": order,
                    "challenge_category": category,
                    **{field: row.get(field) for field in fields if field in row},
                }
            )
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--annotations", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("omnidocbench-80.json"))
    parser.add_argument(
        "--allow-nonofficial-snapshot", action="store_true", help="Só para testes sintéticos"
    )
    parser.add_argument(
        "--check", action="store_true", help="Compara os arquivos existentes sem escrever"
    )
    parser.add_argument(
        "--replace-existing", action="store_true", help="Substitui a amostra fixada"
    )
    args = parser.parse_args()
    annotation_path = (
        args.annotations or args.data_dir / "omnidocbench" / REVISION / "OmniDocBench.json"
    )
    if not annotation_path.is_file():
        parser.error(
            f"Anotações não encontradas: {annotation_path}. Baixe com acessilia-datasets download omnidocbench"
        )
    annotation_sha256 = sha_file(annotation_path)
    if not args.allow_nonofficial_snapshot:
        download_manifest_path = annotation_path.parent / "download-manifest.json"
        if annotation_path.parent.name != REVISION or not download_manifest_path.is_file():
            parser.error(
                f"Snapshot/manifesto inválido: {annotation_path}. Use acessilia-datasets download omnidocbench"
            )
        download_manifest = json.loads(download_manifest_path.read_text(encoding="utf-8"))
        records = [
            item
            for item in download_manifest.get("files", [])
            if item.get("path") == "OmniDocBench.json"
        ]
        if (
            download_manifest.get("dataset_id") != "omnidocbench"
            or download_manifest.get("revision") != REVISION
            or len(records) != 1
            or records[0].get("sha256") != annotation_sha256
            or records[0].get("bytes") != annotation_path.stat().st_size
        ):
            parser.error("Revisão, SHA-256 ou tamanho do JSON diverge do manifesto de download")
    original_records = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(original_records, list):
        parser.error("JSON esperado: lista de páginas")
    if not args.allow_nonofficial_snapshot and len(original_records) != 1651:
        parser.error(f"Quantidade inesperada de páginas: {len(original_records)} (esperadas 1651)")
    pages = [extract_page(record, index) for index, record in enumerate(original_records)]
    manifest = build_manifest(pages, annotation_sha256)
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ids_path = args.output.with_suffix(".ids.txt")
    ids_text = "\n".join(manifest["case_ids"]) + "\n"
    mapping_path = args.output.with_name(args.output.stem + "-mapping.csv")
    mapping_text = _mapping_csv(manifest)
    outputs = ((args.output, manifest_text), (ids_path, ids_text), (mapping_path, mapping_text))
    if args.check:
        if not all(path.is_file() for path, _ in outputs):
            parser.error("Manifesto ou arquivos auxiliares ausentes. Gere primeiro a seleção.")
        for path, expected_text in outputs:
            if path.read_text(encoding="utf-8") != expected_text:
                parser.error(f"Arquivo diverge da seleção reproduzida: {path}")
        print("OK: manifesto, IDs e mapeamento reproduzidos exatamente; nenhum arquivo alterado.")
    else:
        if any(path.exists() for path, _ in outputs) and not args.replace_existing:
            parser.error("Amostra já existe. Use --check ou --replace-existing.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for path, contents in outputs:
            path.write_text(contents, encoding="utf-8")
    print(f"80 páginas distintas selecionadas: {args.output}")
    print(f"SHA-256 dos IDs ordenados: {manifest['selection_sha256']}")
    print(f"Desvio de composição (TV): {manifest['representativeness']['dimensions']}")
    for category in manifest["category_order"]:
        group = manifest["categories"][category]
        sources = dict(collections.Counter(row["data_source"] for row in group))
        print(
            f"{category:16} 16 páginas; níveis={manifest['difficulty_counts'][category]}; origens={sources}"
        )


if __name__ == "__main__":
    main()
