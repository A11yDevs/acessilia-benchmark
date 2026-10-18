"""UTF-8 JSON, atomic artifact writes, hashes and confined relative paths."""

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_path(destination: Path, filename: str) -> Path:
    relative = PurePosixPath(filename)
    if not filename or relative.is_absolute() or ".." in relative.parts or ("\\" in filename):
        raise ValueError(f"Caminho inválido: {filename}")
    path = destination / filename
    if not path.resolve().is_relative_to(destination.resolve()):
        raise ValueError(f"Caminho fora do dataset: {filename}")
    return path


def seal(path: Path) -> None:
    path.with_suffix(path.suffix + ".sha256").write_text(digest(path) + "\n", encoding="ascii")


def verify_seal(path: Path) -> None:
    checksum = path.with_suffix(path.suffix + ".sha256")
    if not checksum.is_file() or checksum.read_text(encoding="ascii").strip() != digest(path):
        raise ValueError(f"Artefato alterado ou sem selo de integridade: {path}")
