"""Explicit filesystem context shared by commands and tests."""

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    @classmethod
    def discover(cls) -> "Workspace":
        configured = os.environ.get("ACESSILIA_BENCHMARK_WORKSPACE")
        if configured:
            return cls(Path(configured))
        for candidate in (Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[3]):
            if (candidate / "datasets/registry.json").is_file():
                return cls(candidate)
        raise ValueError("Execute na raiz do benchmark ou defina ACESSILIA_BENCHMARK_WORKSPACE.")

    @property
    def evaluation_python(self) -> Path:
        return self.root / "evaluation/.venv/bin/python"

    @property
    def data(self) -> Path:
        return self.root / "data"

    def run_dir(self, name: str) -> Path:
        if not re.fullmatch("[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", name):
            raise ValueError(
                "Nome da rodada inválido; use letras, números, ponto, hífen ou sublinhado."
            )
        return self.root / "runs" / name
