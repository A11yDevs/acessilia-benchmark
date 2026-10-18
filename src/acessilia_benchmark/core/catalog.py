"""Obtain and verify immutable dataset snapshots."""

import fnmatch
import json
import os
from datetime import UTC, datetime

from ..io import digest, local_path, read, write
from .workspace import Workspace

MANIFEST = "download-manifest.json"


def load_registry(workspace: Workspace):
    catalog = read(workspace.root / "datasets/registry.json")
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("datasets"), dict):
        raise ValueError("Catálogo de datasets inválido.")
    return catalog["datasets"]


def download(dataset_id, spec, data_dir):
    os.environ.setdefault("HF_HOME", str(data_dir / ".cache/huggingface"))
    try:
        import huggingface_hub
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        raise ValueError("Instale o extra datasets: uv sync --extra datasets.") from None
    destination = data_dir / dataset_id / spec["revision"]
    info = HfApi().dataset_info(spec["repo_id"], revision=spec["revision"], files_metadata=True)
    if info.sha != spec["revision"]:
        raise ValueError("A revisão retornada difere da revisão fixada.")
    files = sorted(
        (
            file
            for file in info.siblings
            if any(
                (fnmatch.fnmatchcase(file.rfilename, pattern) for pattern in spec["allow_patterns"])
            )
        ),
        key=lambda file: file.rfilename,
    )
    if len(files) != spec["expected_files"]:
        raise ValueError("O inventário remoto difere da contagem fixada no catálogo.")
    if any(file.size is None for file in files):
        raise ValueError("O inventário remoto não informa todos os tamanhos.")
    if sum(file.size for file in files) != spec["expected_bytes"]:
        raise ValueError("O tamanho remoto difere do catálogo.")
    for file in files:
        local_path(destination, file.rfilename)
    print(f"{dataset_id}: {len(files)} arquivos → {destination}", flush=True)
    snapshot_download(
        repo_id=spec["repo_id"],
        repo_type="dataset",
        revision=spec["revision"],
        allow_patterns=spec["allow_patterns"],
        local_dir=destination,
        max_workers=8,
    )
    records = []
    for file in files:
        path = local_path(destination, file.rfilename)
        if not path.is_file() or path.stat().st_size != file.size:
            raise ValueError(f"Arquivo ausente ou tamanho incorreto: {file.rfilename}")
        checksum = digest(path)
        if file.lfs and checksum != file.lfs.sha256:
            raise ValueError(f"SHA-256 remoto divergente: {file.rfilename}")
        records.append({"path": file.rfilename, "bytes": file.size, "sha256": checksum})
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "split": spec["split"],
        "source": spec["source"],
        "downloaded_at": datetime.now(UTC).isoformat(),
        "huggingface_hub_version": huggingface_hub.__version__,
        "files": records,
    }
    write(destination / MANIFEST, manifest)
    print(f"Download concluído e manifesto salvo: {destination / MANIFEST}")


def verify(dataset_id, spec, data_dir):
    destination = data_dir / dataset_id / spec["revision"]
    manifest_path = destination / MANIFEST
    if not manifest_path.is_file():
        raise ValueError(f"Manifesto ausente; conclua o download: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    for field, expected in (
        ("schema_version", 1),
        ("dataset_id", dataset_id),
        ("repo_id", spec["repo_id"]),
        ("revision", spec["revision"]),
        ("split", spec["split"]),
    ):
        if manifest.get(field) != expected:
            raise ValueError(f"Manifesto incompatível: {field}")
    files = manifest["files"]
    if len(files) != spec["expected_files"] or len({f["path"] for f in files}) != len(files):
        raise ValueError("Inventário incompleto ou com caminhos duplicados.")
    if sum(f["bytes"] for f in files) != spec["expected_bytes"]:
        raise ValueError("Tamanho total do manifesto difere do catálogo.")
    for file in files:
        path = local_path(destination, file["path"])
        if not path.is_file():
            raise ValueError(f"Arquivo ausente: {file['path']}")
        if path.stat().st_size != file["bytes"] or digest(path) != file["sha256"]:
            raise ValueError(f"Arquivo alterado ou corrompido: {file['path']}")
    print(f"{dataset_id}: {len(files)} arquivos verificados, revisão {spec['revision']}.")
