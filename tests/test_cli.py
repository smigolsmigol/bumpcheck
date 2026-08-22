import contextlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from pydantic_canary.capture import capture
from pydantic_canary.cli import DEFAULT_PYTHON_VERSION, DEFAULT_WATCHES, _parser, main

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
            patch("pydantic_canary.cli.capture", side_effect=[baseline, candidate]),
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
            patch("pydantic_canary.cli.capture", return_value=artifact) as capture_mock,
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


if __name__ == "__main__":
    unittest.main()
