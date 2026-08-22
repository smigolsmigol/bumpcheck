import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bumpcheck._worker as worker


class _Distribution:
    version = "1.2.3"

    def __init__(self, direct_url):
        self.direct_url = direct_url

    def read_text(self, name):
        if name != "direct_url.json":
            raise AssertionError(name)
        return self.direct_url


class WorkerTests(unittest.TestCase):
    def test_distribution_record_preserves_direct_url_provenance(self):
        module_spec = type("ModuleSpec", (), {"origin": "/package/__init__.py"})()
        expectations = [
            (
                '{"url":"https://example.invalid/package"}',
                {"url": "https://example.invalid/package"},
            ),
            ("not-json", {"invalid_json": True}),
            (None, None),
        ]

        for raw_direct_url, expected in expectations:
            with (
                self.subTest(raw_direct_url=raw_direct_url),
                patch.object(worker.importlib.util, "find_spec", return_value=module_spec),
                patch.object(
                    worker.importlib.metadata,
                    "distribution",
                    return_value=_Distribution(raw_direct_url),
                ),
            ):
                record = worker._distribution_record("example", "example_module")

            self.assertTrue(record["found"])
            self.assertEqual(record["version"], "1.2.3")
            self.assertEqual(record["module_origin"], "/package/__init__.py")
            self.assertEqual(record["direct_url"], expected)

    def test_extracts_stable_pydantic_errors(self):
        def errors(_self, **kwargs):
            self.assertEqual(
                kwargs,
                {"include_url": False, "include_context": False, "include_input": False},
            )
            return [
                {"loc": ("value", 0), "type": "greater_than"},
                "ignored",
                {},
                {"loc": ("other",), "type": "missing"},
            ]

        validation_error = type(
            "ValidationError",
            (Exception,),
            {"__module__": "pydantic.fake", "errors": errors},
        )()

        self.assertEqual(
            worker._pydantic_errors(validation_error),
            [
                {"loc": ["value", 0], "type": "greater_than"},
                {"loc": ["other"], "type": "missing"},
            ],
        )

    def test_supports_legacy_pydantic_errors_signature(self):
        def errors(_self, *args, **kwargs):
            if kwargs:
                raise TypeError("legacy signature")
            return [{"loc": (), "type": "legacy"}]

        validation_error = type(
            "ValidationError",
            (Exception,),
            {"__module__": "pydantic_core.fake", "errors": errors},
        )()
        missing_errors_method = type(
            "ValidationError",
            (Exception,),
            {"__module__": "pydantic.fake", "errors": None},
        )()

        self.assertEqual(worker._pydantic_errors(validation_error), [{"loc": [], "type": "legacy"}])
        self.assertIsNone(worker._pydantic_errors(missing_errors_method))

    def test_rejects_invalid_input_documents(self):
        invalid_documents = [
            (b"\xff", False, "inputs must be valid JSON"),
            (b"[NaN]", False, "inputs must be valid JSON"),
            (b"{}", False, "JSON array"),
            (b"[]", False, "at least one case"),
            (b'{"cases":[]}', False, "at least one case"),
            (b'{"cases":[{}]}', False, "containing 'inputs'"),
            (b'{"cases":[{"name":1,"inputs":null}]}', False, "name must be a string"),
            (b"\xff", True, "valid UTF-8 JSON"),
            (b"\n\n", True, "at least one case"),
        ]

        for raw_bytes, json_lines, message in invalid_documents:
            with (
                self.subTest(raw_bytes=raw_bytes, json_lines=json_lines),
                self.assertRaisesRegex(worker.CaseProtocolError, message),
            ):
                worker._input_cases(raw_bytes, json_lines=json_lines)

    def test_rejects_case_without_callable_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            case = Path(tmp_dir) / "case.py"
            case.write_text("run = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(worker.CaseProtocolError, "callable run"):
                worker._load_and_run(case)

    def test_rejects_case_with_wrong_run_signature(self):
        cases = [
            ("def run(value):\n    return value\n", None, r"run\(\)"),
            ("def run():\n    return None\n", [("first", None)], r"run\(value\)"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, (source, inputs, message) in enumerate(cases):
                case = Path(tmp_dir) / f"case_{index}.py"
                case.write_text(source, encoding="utf-8")
                with (
                    self.subTest(source=source),
                    self.assertRaisesRegex(worker.CaseProtocolError, message),
                ):
                    worker._load_and_run(case, inputs)

    def test_batch_identifies_non_json_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            case = Path(tmp_dir) / "case.py"
            case.write_text("def run(value):\n    return object()\n", encoding="utf-8")

            with self.assertRaisesRegex(worker.CaseProtocolError, "input 'first'"):
                worker._load_and_run(case, [("first", None)])

    def test_batch_records_application_exception(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            case = Path(tmp_dir) / "case.py"
            case.write_text("def run(value):\n    raise ValueError(value)\n", encoding="utf-8")

            result = worker._load_and_run(case, [("first", "broken")])

        self.assertEqual(result["kind"], "batch")
        self.assertEqual(result["items"][0]["outcome"]["type"], "builtins.ValueError")

    def test_rejects_unloadable_case(self):
        with (
            patch.object(worker.importlib.util, "spec_from_file_location", return_value=None),
            self.assertRaisesRegex(worker.CaseProtocolError, "could not load"),
        ):
            worker._load_and_run(Path("missing.py"))

    def test_parse_watch_defaults_module_and_rejects_empty_name(self):
        self.assertEqual(worker._parse_watch("pydantic-core"), ("pydantic-core", "pydantic_core"))
        self.assertEqual(worker._parse_watch("dist:module"), ("dist", "module"))
        with self.assertRaises(argparse.ArgumentTypeError):
            worker._parse_watch(":module")


if __name__ == "__main__":
    unittest.main()
