"""One benchmark request → Acessilia canonical pipeline → benchmark Markdown.

Run with the Acessilia interpreter/environment, not the evaluator environment.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", default="normal", choices=["normal"])
    parser.add_argument("--engine", choices=["pipeline", "structure"], default="pipeline")
    parser.add_argument("--provider")
    args = parser.parse_args()
    if args.provider and args.engine != "structure":
        parser.error("--provider requer --engine structure.")
    args.output = args.output.expanduser().absolute()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if set(request) != {"id", "images"} or not request["images"]:
        raise ValueError("Request inválido; somente id e imagens são permitidos.")
    if any(not Path(path).is_file() for path in request["images"]):
        raise ValueError("Imagem de entrada ausente.")
    repo = args.repo.resolve()
    adapter_directory = Path(__file__).resolve().parent
    sys.path[:] = [path for path in sys.path if Path(path or ".").resolve() != adapter_directory]
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "libs/docstruct/src"))
    os.chdir(repo)
    from backend.config.settings import settings
    from docstruct.export.markdown import document_to_markdown

    if (
        args.engine == "pipeline"
        and settings.pipeline_engine == "pddl"
        and settings.pddl_execute_dry_run
    ):
        raise RuntimeError("Desative PDDL_EXECUTE_DRY_RUN para avaliar conversão real.")
    images = [Path(path) for path in request["images"]]
    with tempfile.TemporaryDirectory(prefix="acessilia-benchmark-") as temporary:
        source = images[0]
        if len(images) > 1:
            source = Path(temporary) / "window.pdf"
            pack_images(images, source)
        if args.engine == "structure":
            from scripts.bench.core import payload_to_canonical
            from scripts.bench.toolbox import extract_structure

            canonical = payload_to_canonical(extract_structure(source, args.provider))
        else:
            from backend.service import process

            canonical = asyncio.run(process(source, mode=args.mode))
        execution_metadata = canonical.get("metadata") or canonical.get("canonical_metadata") or {}
        status = execution_metadata.get("pddl_execution_status")
        if status in {"failed", "replan-required", "dry-run-completed"}:
            raise RuntimeError(f"Pipeline sem execução válida: {status}")
        markdown = document_to_markdown(canonical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    public_fields = (
        "ai_client",
        "ollama_model",
        "openrouter_model",
        "openrouter_max_tokens",
        "data_agent_max_tokens",
        "vision_region_max_tokens",
        "structurer",
        "pipeline_engine",
        "fusion_mode",
        "toolbox_provider",
        "toolbox_layout_provider",
        "toolbox_pdf_provider",
        "toolbox_math_provider",
        "toolbox_math_recognize_provider",
        "toolbox_ocr_provider",
        "toolbox_page_ocr_provider",
        "toolbox_adjudicate_provider",
        "toolbox_use_remote_cache",
        "pddl_execute_dry_run",
        "pddl_planner_backend",
    )
    metadata = {
        "python_version": sys.version,
        "settings": {name: getattr(settings, name, None) for name in public_fields},
        "mode": args.mode,
        "engine": args.engine,
        "provider": args.provider,
        "execution_status": status,
        "technical_warnings": canonical.get("technical_warnings"),
        "processing_diagnostics": {
            key: execution_metadata.get(key)
            for key in (
                "pddl_unsatisfied_obligations",
                "pddl_visual_failures",
                "pddl_fusion",
                "pddl_media_inspection",
            )
        },
        "prediction_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "input_representation": "image" if len(images) == 1 else "lossless_raster_pdf_72dpi",
    }
    args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


def pack_images(images: list[Path], output: Path) -> None:
    """Embed original image streams in PDF; do not recompress benchmark images."""
    import fitz

    with fitz.open() as document:
        for image in images:
            pixmap = fitz.Pixmap(str(image))
            page = document.new_page(width=pixmap.width, height=pixmap.height)
            page.insert_image(page.rect, filename=str(image))
        document.save(str(output), deflate=True)


if __name__ == "__main__":
    main()
