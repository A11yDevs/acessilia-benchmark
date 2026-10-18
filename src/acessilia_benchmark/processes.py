"""Bounded subprocess execution with cleanup of owned process groups."""

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    seconds: float
    timed_out: bool = False


def git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *arguments], text=True).strip()


def run_logged(
    command: list[str],
    log: Path,
    *,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> ProcessResult:
    if timeout <= 0:
        raise ValueError("Timeout deve ser positivo.")
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
            return ProcessResult(code, time.perf_counter() - started)
        except BaseException as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if isinstance(error, subprocess.TimeoutExpired):
                return ProcessResult(process.returncode, time.perf_counter() - started, True)
            raise
