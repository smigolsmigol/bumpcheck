"""Run one contract case under a target Python interpreter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

Watch = tuple[str, str]


class CaptureError(RuntimeError):
    """The target environment did not produce a trustworthy artifact."""


def _executable(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    resolved = shutil.which(raw)
    path = Path(resolved if resolved is not None else raw).expanduser().absolute()
    if not path.is_file():
        raise CaptureError(f"{label} executable does not exist: {path}")
    return path


def _file(value: str | os.PathLike[str], label: str) -> Path:
    path = Path(value).expanduser().absolute()
    if not path.is_file():
        raise CaptureError(f"{label} does not exist: {path}")
    return path


def _worker_command(
    case_path: Path, watches: list[Watch], inputs_path: Path | None = None
) -> list[str]:
    worker_path = Path(__file__).with_name("_worker.py")
    command = ["python", "-I", "-B", str(worker_path), "--case", str(case_path)]
    if inputs_path is not None:
        command.extend(("--inputs", str(inputs_path)))
    for distribution, module in watches:
        command.extend(("--watch", f"{distribution}:{module}"))
    return command


def _run_worker(
    command: list[str],
    *,
    watches: list[Watch],
    timeout: float,
    expected_executable: Path | None = None,
    result_path: Path | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"Case exceeded {timeout:g}s timeout") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or "no output"
        raise CaptureError(f"Worker exited {completed.returncode}: {detail}")

    if result_path is None:
        artifact_bytes = completed.stdout
    else:
        try:
            artifact_bytes = result_path.read_bytes()
        except FileNotFoundError as exc:
            raise CaptureError("Worker omitted result artifact") from exc
        except OSError as exc:
            raise CaptureError("Worker result artifact could not be read") from exc

    try:
        artifact = json.loads(artifact_bytes)
    except UnicodeDecodeError as exc:
        raise CaptureError("Worker returned non-UTF-8 output") from exc
    except json.JSONDecodeError as exc:
        raise CaptureError("Worker returned malformed JSON") from exc
    if not isinstance(artifact, dict):
        raise CaptureError("Worker returned malformed artifact")

    if result_path is not None:
        try:
            artifact["stdout"] = completed.stdout.decode("utf-8")
            artifact["stderr"] = completed.stderr.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CaptureError("Worker emitted non-UTF-8 output") from exc

    if artifact.get("schema_version") != 1:
        raise CaptureError("Worker returned an unsupported schema version")
    if artifact.get("protocol_error"):
        raise CaptureError(str(artifact["protocol_error"]))

    environment = artifact.get("environment")
    if not isinstance(environment, dict):
        raise CaptureError("Worker omitted environment provenance")
    if expected_executable is not None:
        observed_executable = Path(str(environment.get("executable", ""))).absolute()
        if observed_executable != expected_executable:
            raise CaptureError(
                "Target executable mismatch: "
                f"requested {expected_executable}, observed {observed_executable}"
            )

    distributions = environment.get("distributions")
    if not isinstance(distributions, list) or len(distributions) != len(watches):
        raise CaptureError("Worker returned incomplete distribution provenance")
    missing = [
        str(item.get("distribution"))
        for item in distributions
        if not isinstance(item, dict) or not item.get("found") or not item.get("module_origin")
    ]
    if missing:
        raise CaptureError(
            f"Watched distribution is missing or not importable: {', '.join(missing)}"
        )

    return artifact


def _run_capture(
    command: list[str],
    *,
    watches: list[Watch],
    timeout: float,
    expected_executable: Path | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="bumpcheck-") as directory:
        result_path = Path(directory) / "result.json"
        command.extend(("--result", str(result_path)))
        return _run_worker(
            command,
            watches=watches,
            timeout=timeout,
            expected_executable=expected_executable,
            result_path=result_path,
        )


def capture(
    python: str | os.PathLike[str],
    case: str | os.PathLike[str],
    *,
    inputs: str | os.PathLike[str] | None = None,
    watches: Iterable[Watch] = (),
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Capture one case without installing Bumpcheck in the target environment."""

    python_path = _executable(python, "Python")
    case_path = _file(case, "Case")
    inputs_path = None if inputs is None else _file(inputs, "Inputs")
    if timeout <= 0:
        raise CaptureError("Timeout must be greater than zero")

    watch_values = list(watches)
    command = _worker_command(case_path, watch_values, inputs_path)
    command[0] = str(python_path)
    return _run_capture(
        command,
        watches=watch_values,
        timeout=timeout,
        expected_executable=python_path,
    )


def capture_requirements(
    requirements: Iterable[str],
    case: str | os.PathLike[str],
    *,
    inputs: str | os.PathLike[str] | None = None,
    watches: Iterable[Watch] = (),
    timeout: float = 30.0,
    uv: str | os.PathLike[str] = "uv",
    python_version: str | None = None,
) -> dict[str, Any]:
    """Capture one case in an isolated environment created by uv."""

    uv_path = _executable(uv, "uv")
    case_path = _file(case, "Case")
    inputs_path = None if inputs is None else _file(inputs, "Inputs")
    if timeout <= 0:
        raise CaptureError("Timeout must be greater than zero")

    requirement_values = tuple(requirements)
    if not requirement_values or any(not value.strip() for value in requirement_values):
        raise CaptureError("At least one non-empty requirement is required")
    watch_values = list(watches)
    command = [
        str(uv_path),
        "run",
        "--isolated",
        "--no-project",
        "--no-config",
        "--no-progress",
    ]
    if python_version is not None:
        command.extend(("--python", python_version))
    for requirement in requirement_values:
        command.extend(("--with", requirement))
    command.append("--")
    command.extend(_worker_command(case_path, watch_values, inputs_path))
    return _run_capture(command, watches=watch_values, timeout=timeout)
