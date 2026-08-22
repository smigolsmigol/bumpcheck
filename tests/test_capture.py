import json
import locale
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_canary._worker import CaseProtocolError, _input_cases
from pydantic_canary.capture import CaptureError, _run_worker, capture, capture_requirements

CASES = Path(__file__).parent / "cases"


class CaptureTests(unittest.TestCase):
    @staticmethod
    def _artifact(**updates):
        artifact = {
            "schema_version": 1,
            "protocol_error": None,
            "environment": {"executable": sys.executable, "distributions": []},
        }
        artifact.update(updates)
        return artifact

    def test_captures_return_value_and_provenance(self):
        artifact = capture(sys.executable, CASES / "return_value.py")

        self.assertEqual(artifact["outcome"], {"kind": "return", "value": {"answer": 42}})
        self.assertEqual(artifact["environment"]["executable"], sys.executable)
        self.assertEqual(len(artifact["case"]["sha256"]), 64)

    def test_case_module_supports_standard_decorators(self):
        artifact = capture(sys.executable, CASES / "dataclass_value.py")

        self.assertEqual(artifact["outcome"], {"kind": "return", "value": {"answer": 42}})

    def test_replays_json_array(self):
        artifact = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )

        self.assertEqual(artifact["inputs"]["count"], 2)
        self.assertEqual(len(artifact["inputs"]["sha256"]), 64)
        self.assertEqual(
            artifact["outcome"]["items"],
            [
                {
                    "index": 0,
                    "name": "0",
                    "outcome": {"kind": "return", "value": {"answer": 42}},
                },
                {
                    "index": 1,
                    "name": "1",
                    "outcome": {"kind": "return", "value": {"answer": 1}},
                },
            ],
        )

    def test_replays_pydantic_evals_json(self):
        artifact = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "evals_inputs.json",
        )

        self.assertEqual(
            [item["name"] for item in artifact["outcome"]["items"]],
            ["existing-answer", "zero"],
        )

    def test_records_input_count_when_case_import_fails(self):
        artifact = capture(
            sys.executable,
            CASES / "import_failure.py",
            inputs=CASES / "inputs.json",
        )

        self.assertEqual(artifact["inputs"]["count"], 2)
        self.assertEqual(artifact["outcome"]["type"], "builtins.RuntimeError")

    def test_preserves_empty_pydantic_evals_case_name(self):
        cases = _input_cases(b'{"cases":[{"name":"","inputs":null}]}')

        self.assertEqual(cases, [("", None)])

    def test_replays_json_lines_and_names_source_lines(self):
        cases = _input_cases(b'{"answer":42}\n\n{"answer":0}\n', json_lines=True)

        self.assertEqual(cases, [("line-1", {"answer": 42}), ("line-3", {"answer": 0})])

    def test_replays_single_json_line_by_file_suffix(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            inputs = Path(tmp_dir) / "inputs.jsonl"
            inputs.write_text('{"answer":41}\n', encoding="utf-8")
            artifact = capture(sys.executable, CASES / "input_value.py", inputs=inputs)

        self.assertEqual(artifact["inputs"]["count"], 1)
        self.assertEqual(artifact["outcome"]["items"][0]["name"], "line-1")
        self.assertEqual(
            artifact["outcome"]["items"][0]["outcome"],
            {"kind": "return", "value": {"answer": 42}},
        )

    def test_rejects_invalid_json_line_with_source_line(self):
        with self.assertRaisesRegex(CaseProtocolError, "inputs line 2 must be valid JSON"):
            _input_cases(b'{"answer":42}\nnot-json\n', json_lines=True)

    def test_rejects_non_json_result(self):
        with self.assertRaisesRegex(CaptureError, "JSON-compatible"):
            capture(sys.executable, CASES / "non_json.py")

    def test_rejects_missing_watched_distribution(self):
        with self.assertRaisesRegex(CaptureError, "missing or not importable"):
            capture(
                sys.executable,
                CASES / "return_value.py",
                watches=(("definitely-not-installed-canary-package", "not_a_real_module"),),
            )

    def test_enforces_timeout(self):
        with self.assertRaisesRegex(CaptureError, "exceeded"):
            capture(sys.executable, CASES / "timeout.py", timeout=0.05)

    def test_preserves_utf8_worker_error_output(self):
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.buffer.write(b'failure: ' + bytes.fromhex('e28da0')); "
            "raise SystemExit(1)",
        ]

        locale_decoder = (
            "locale.getencoding"
            if hasattr(locale, "getencoding")
            else "locale.getpreferredencoding"
        )
        with (
            patch(locale_decoder, return_value="cp1252"),
            self.assertRaisesRegex(CaptureError, r"failure: \u2360"),
        ):
            _run_worker(command, watches=[], timeout=10)

    def test_rejects_non_utf8_worker_output(self):
        command = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(bytes.fromhex('ff'))",
        ]

        with self.assertRaisesRegex(CaptureError, "non-UTF-8"):
            _run_worker(command, watches=[], timeout=10)

    def test_validates_capture_paths_and_timeout(self):
        missing = CASES / "definitely-missing.py"
        checks = [
            ((missing, CASES / "return_value.py"), {}, "Python executable does not exist"),
            ((sys.executable, missing), {}, "Case does not exist"),
            (
                (sys.executable, CASES / "return_value.py"),
                {"inputs": missing},
                "Inputs does not exist",
            ),
            ((sys.executable, CASES / "return_value.py"), {"timeout": 0}, "greater than zero"),
        ]

        for args, kwargs, message in checks:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(CaptureError, message),
            ):
                capture(*args, **kwargs)

    def test_rejects_untrustworthy_worker_artifacts(self):
        valid = self._artifact()
        invalid_artifacts = [
            (b"not-json", "malformed JSON", None, []),
            (json.dumps({**valid, "schema_version": 2}).encode(), "unsupported schema", None, []),
            (json.dumps({**valid, "protocol_error": "bad case"}).encode(), "bad case", None, []),
            (json.dumps({**valid, "environment": None}).encode(), "omitted environment", None, []),
            (
                json.dumps(
                    {
                        **valid,
                        "environment": {"executable": "different-python", "distributions": []},
                    }
                ).encode(),
                "Target executable mismatch",
                Path(sys.executable).absolute(),
                [],
            ),
            (
                json.dumps(
                    {**valid, "environment": {"executable": sys.executable, "distributions": []}}
                ).encode(),
                "incomplete distribution provenance",
                None,
                [("example", "example")],
            ),
            (
                json.dumps(
                    {
                        **valid,
                        "environment": {
                            "executable": sys.executable,
                            "distributions": [{"distribution": "example", "found": True}],
                        },
                    }
                ).encode(),
                "missing or not importable",
                None,
                [("example", "example")],
            ),
        ]

        for stdout, message, expected_executable, watches in invalid_artifacts:
            completed = subprocess.CompletedProcess(["worker"], 0, stdout=stdout, stderr=b"")
            with (
                self.subTest(message=message),
                patch("pydantic_canary.capture.subprocess.run", return_value=completed),
                self.assertRaisesRegex(CaptureError, message),
            ):
                _run_worker(
                    ["worker"],
                    watches=watches,
                    timeout=10,
                    expected_executable=expected_executable,
                )

    def test_capture_requirements_builds_isolated_command(self):
        sentinel = {"captured": True}
        with patch("pydantic_canary.capture._run_worker", return_value=sentinel) as run_worker:
            result = capture_requirements(
                ("pydantic==2.10.0", "example-extra"),
                CASES / "input_value.py",
                inputs=CASES / "inputs.json",
                watches=(("pydantic", "pydantic"),),
                uv=sys.executable,
                python_version="3.12",
            )

        command = run_worker.call_args.args[0]
        self.assertEqual(result, sentinel)
        self.assertEqual(
            command[:6],
            [
                str(Path(sys.executable).absolute()),
                "run",
                "--isolated",
                "--no-project",
                "--no-config",
                "--no-progress",
            ],
        )
        self.assertIn("--python", command)
        self.assertIn("3.12", command)
        self.assertEqual(command.count("--with"), 2)
        self.assertIn("--inputs", command)
        self.assertIn("pydantic:pydantic", command)

    def test_capture_requirements_validates_timeout_and_requirements(self):
        invalid = [
            ((), 30, "non-empty requirement"),
            (("pydantic", " "), 30, "non-empty requirement"),
            (("pydantic",), 0, "greater than zero"),
        ]
        for requirements, timeout, message in invalid:
            with (
                self.subTest(requirements=requirements, timeout=timeout),
                self.assertRaisesRegex(CaptureError, message),
            ):
                capture_requirements(
                    requirements,
                    CASES / "return_value.py",
                    timeout=timeout,
                    uv=sys.executable,
                )


if __name__ == "__main__":
    unittest.main()
