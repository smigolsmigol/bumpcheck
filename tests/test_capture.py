import locale
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_canary._worker import CaseProtocolError, _input_cases
from pydantic_canary.capture import CaptureError, _run_worker, capture

CASES = Path(__file__).parent / "cases"


class CaptureTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
