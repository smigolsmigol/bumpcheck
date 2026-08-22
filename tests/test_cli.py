import argparse
import contextlib
import io
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from bumpcheck.capture import CaptureError, capture
from bumpcheck.cli import DEFAULT_PYTHON_VERSION, DEFAULT_WATCHES, _parser, _watch, main

CASES = Path(__file__).parent / "cases"


class CliTests(unittest.TestCase):
    def test_requirement_targets_default_to_controller_python_minor(self):
        args = _parser().parse_args(
            [
                "check",
                str(CASES / "return_value.py"),
                "--baseline",
                "example==1",
                "--candidate",
                "example==2",
            ]
        )

        self.assertEqual(args.python_version, DEFAULT_PYTHON_VERSION)
        self.assertEqual(args.timeout, 30.0)

    def test_same_environment_returns_success(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("UNCHANGED return_value", stdout.getvalue())

    def test_same_environment_reports_input_count(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "check",
                    str(CASES / "input_value.py"),
                    "--inputs",
                    str(CASES / "inputs.json"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("UNCHANGED input_value (2 inputs)", stdout.getvalue())

    def test_reports_batch_level_warning_change(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["warnings"] = [{"category": "builtins.DeprecationWarning", "message": "changed"}]
        stdout = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", side_effect=[baseline, candidate]),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "input_value.py"),
                    "--inputs",
                    str(CASES / "inputs.json"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("batch-level warnings or captured output changed", stdout.getvalue())

    def test_rejects_watch_with_no_watch(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--watch",
                    "example",
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("cannot be combined", stderr.getvalue())

    def test_watch_extends_default_watches(self):
        artifact = capture(sys.executable, CASES / "return_value.py")
        stdout = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", return_value=artifact) as capture_mock,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--watch",
                    "example:example_module",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            capture_mock.call_args_list[0].kwargs["watches"],
            (*DEFAULT_WATCHES, ("example", "example_module")),
        )

    def test_requirement_targets_use_isolated_capture(self):
        artifact = capture(sys.executable, CASES / "return_value.py")
        stdout = io.StringIO()
        with (
            patch(
                "bumpcheck.cli.capture_requirements", return_value=artifact
            ) as requirement_capture,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline",
                    "pydantic==2.10.0",
                    "--candidate",
                    "pydantic==2.13.4",
                    "--with",
                    "example-extra",
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(requirement_capture.call_count, 2)
        self.assertEqual(
            requirement_capture.call_args_list[0].args[0],
            ("pydantic==2.10.0", "example-extra"),
        )
        self.assertIn("UNCHANGED return_value", stdout.getvalue())

    def test_json_output_is_machine_readable(self):
        artifact = capture(sys.executable, CASES / "return_value.py")
        stdout = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", return_value=artifact),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertFalse(json.loads(stdout.getvalue())["changed"])

    def test_capture_error_is_reported(self):
        stderr = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", side_effect=CaptureError("broken target")),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("ERROR broken target", stderr.getvalue())

    def test_reports_changed_single_outcome(self):
        baseline = capture(sys.executable, CASES / "return_value.py")
        candidate = deepcopy(baseline)
        candidate["outcome"]["value"]["answer"] = 43
        stdout = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", side_effect=[baseline, candidate]),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "return_value.py"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            'CHANGED return_value: return {"answer":42} -> return {"answer":43}', stdout.getvalue()
        )

    def test_reports_first_changed_batch_input(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["outcome"]["items"][1]["outcome"]["value"]["answer"] = 2
        stdout = io.StringIO()
        with (
            patch("bumpcheck.cli.capture", side_effect=[baseline, candidate]),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "check",
                    str(CASES / "input_value.py"),
                    "--inputs",
                    str(CASES / "inputs.json"),
                    "--baseline-python",
                    sys.executable,
                    "--candidate-python",
                    sys.executable,
                    "--no-watch",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("CHANGED input_value: 1/2 inputs; first 1", stdout.getvalue())

    def test_watch_parser_rejects_empty_distribution(self):
        self.assertEqual(_watch("pydantic-core"), ("pydantic-core", "pydantic_core"))
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "watch must name"):
            _watch(":module")

    def test_module_entrypoint_displays_help(self):
        completed = subprocess.run(
            [sys.executable, "-m", "bumpcheck", "--help"],
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn(b"Catch Pydantic runtime behavior changes", completed.stdout)


if __name__ == "__main__":
    unittest.main()
