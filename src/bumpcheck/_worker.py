"""Standalone worker executed by target Python interpreters.

Keep this module compatible with Python 3.9 and free of package-relative imports.
"""

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import inspect
import io
import json
import os
import platform
import sys
import warnings
from pathlib import Path

SCHEMA_VERSION = 1


class CaseProtocolError(Exception):
    pass


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _distribution_record(distribution_name, module_name):
    module_spec = importlib.util.find_spec(module_name)
    module_origin = None if module_spec is None else module_spec.origin

    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return {
            "distribution": distribution_name,
            "found": False,
            "module": module_name,
            "module_origin": module_origin,
        }

    direct_url = distribution.read_text("direct_url.json")
    if direct_url is not None:
        try:
            direct_url = json.loads(direct_url)
        except json.JSONDecodeError:
            direct_url = {"invalid_json": True}

    return {
        "distribution": distribution_name,
        "direct_url": direct_url,
        "found": True,
        "module": module_name,
        "module_origin": module_origin,
        "version": distribution.version,
    }


def _environment(watches):
    value = {
        "distributions": [
            _distribution_record(distribution, module) for distribution, module in watches
        ],
        "executable": sys.executable,
        "executable_realpath": os.path.realpath(sys.executable),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }
    value["fingerprint"] = hashlib.sha256(_canonical_bytes(value)).hexdigest()
    return value


def _pydantic_errors(exc):
    exception_type = type(exc)
    if exception_type.__name__ != "ValidationError" or not exception_type.__module__.startswith(
        ("pydantic", "pydantic_core")
    ):
        return None

    errors_method = getattr(exc, "errors", None)
    if not callable(errors_method):
        return None

    try:
        errors = errors_method(include_url=False, include_context=False, include_input=False)
    except TypeError:
        errors = errors_method()

    records = []
    for error in errors:
        if not isinstance(error, dict) or error.get("type") is None:
            continue
        location = error.get("loc", ())
        if not isinstance(location, (list, tuple)):
            location = (location,)
        records.append(
            {
                "loc": [item if isinstance(item, (str, int)) else str(item) for item in location],
                "type": str(error["type"]),
            }
        )
    return sorted(records, key=lambda record: (record["type"], _canonical_bytes(record["loc"])))


def _exception_record(exc):
    exception_type = type(exc)
    pydantic_errors = _pydantic_errors(exc)
    return {
        "kind": "exception",
        "message": str(exc),
        "pydantic_errors": pydantic_errors,
        "pydantic_error_types": (
            None if pydantic_errors is None else [error["type"] for error in pydantic_errors]
        ),
        "type": f"{exception_type.__module__}.{exception_type.__qualname__}",
    }


def _return_outcome(run, *args):
    value = run(*args)
    try:
        _canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise CaseProtocolError(f"run() must return a JSON-compatible value: {exc}") from exc
    return {"kind": "return", "value": value}


def _json_lines_cases(raw_bytes):
    try:
        lines = raw_bytes.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise CaseProtocolError(f"inputs must be valid UTF-8 JSON: {exc}") from exc

    cases = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            _canonical_bytes(item)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CaseProtocolError(f"inputs line {line_number} must be valid JSON: {exc}") from exc
        cases.append((f"line-{line_number}", item))

    if not cases:
        raise CaseProtocolError("inputs must contain at least one case")
    return cases


def _input_cases(raw_bytes, *, json_lines=False):
    if json_lines:
        return _json_lines_cases(raw_bytes)

    try:
        value = json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise CaseProtocolError(f"inputs must be valid JSON: {exc}") from exc

    try:
        _canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise CaseProtocolError(f"inputs must be valid JSON: {exc}") from exc

    if isinstance(value, list):
        cases = [(str(index), item) for index, item in enumerate(value)]
    elif isinstance(value, dict) and isinstance(value.get("cases"), list):
        cases = []
        for index, item in enumerate(value["cases"]):
            if not isinstance(item, dict) or "inputs" not in item:
                raise CaseProtocolError(
                    f"inputs case {index} must be an object containing 'inputs'"
                )
            name = item.get("name")
            if name is not None and not isinstance(name, str):
                raise CaseProtocolError(f"inputs case {index} name must be a string or null")
            cases.append((str(index) if name is None else name, item["inputs"]))
    else:
        raise CaseProtocolError("inputs must be a JSON array or an object with a 'cases' array")

    if not cases:
        raise CaseProtocolError("inputs must contain at least one case")
    return cases


def _load_and_run(case_path, input_cases=None):
    spec = importlib.util.spec_from_file_location("bumpcheck_case", str(case_path))
    if spec is None or spec.loader is None:
        raise CaseProtocolError("could not load case module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if not callable(run):
        raise CaseProtocolError("case must define callable run()")

    try:
        inspect.signature(run).bind(*(() if input_cases is None else (object(),)))
    except (TypeError, ValueError) as exc:
        expected = "run()" if input_cases is None else "run(value)"
        raise CaseProtocolError(f"case must define callable {expected}: {exc}") from exc

    if input_cases is None:
        return _return_outcome(run)

    items = []
    for index, (name, value) in enumerate(input_cases):
        try:
            outcome = _return_outcome(run, value)
        except CaseProtocolError as exc:
            raise CaseProtocolError(f"input {name!r}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - application exceptions are observed per input
            outcome = _exception_record(exc)
        items.append({"index": index, "name": name, "outcome": outcome})
    return {"items": items, "kind": "batch"}


def capture(case_path, watches, inputs_path=None):
    case_bytes = case_path.read_bytes()
    case_sha256 = hashlib.sha256(case_bytes).hexdigest()
    inputs_bytes = None if inputs_path is None else inputs_path.read_bytes()
    inputs_record = (
        None
        if inputs_path is None
        else {
            "name": inputs_path.name,
            "sha256": hashlib.sha256(inputs_bytes).hexdigest(),
        }
    )
    environment = _environment(watches)
    stdout = io.StringIO()
    stderr = io.StringIO()
    protocol_error = None
    outcome = None

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                input_cases = (
                    None
                    if inputs_bytes is None
                    else _input_cases(
                        inputs_bytes,
                        json_lines=inputs_path.suffix.lower() in {".jsonl", ".ndjson"},
                    )
                )
                if inputs_record is not None:
                    inputs_record["count"] = len(input_cases)
                outcome = _load_and_run(case_path, input_cases)
            except CaseProtocolError as exc:
                protocol_error = str(exc)
            except Exception as exc:  # noqa: BLE001 - application exceptions are the observed result
                outcome = _exception_record(exc)

    try:
        final_case_sha256 = hashlib.sha256(case_path.read_bytes()).hexdigest()
    except OSError:
        final_case_sha256 = None
    if final_case_sha256 != case_sha256:
        protocol_error = "case bytes changed during execution"
    if inputs_path is not None:
        try:
            final_inputs_sha256 = hashlib.sha256(inputs_path.read_bytes()).hexdigest()
        except OSError:
            final_inputs_sha256 = None
        if final_inputs_sha256 != inputs_record["sha256"]:
            protocol_error = "input bytes changed during execution"

    warning_records = [
        {
            "category": f"{item.category.__module__}.{item.category.__qualname__}",
            "message": str(item.message),
        }
        for item in caught_warnings
    ]
    result = {
        "case": {
            "name": case_path.stem,
            "sha256": case_sha256,
        },
        "environment": environment,
        "inputs": inputs_record,
        "outcome": outcome,
        "protocol_error": protocol_error,
        "schema_version": SCHEMA_VERSION,
        "stderr": stderr.getvalue(),
        "stdout": stdout.getvalue(),
        "warnings": warning_records,
    }
    return result


def _parse_watch(value):
    distribution, separator, module = value.partition(":")
    if not distribution:
        raise argparse.ArgumentTypeError("watch must name a distribution")
    return distribution, module if separator else distribution.replace("-", "_")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--watch", action="append", default=[], type=_parse_watch)
    args = parser.parse_args(argv)
    result = capture(args.case, args.watch, args.inputs)
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
