import sys
import unittest
from copy import deepcopy
from pathlib import Path

from pydantic_canary.capture import capture
from pydantic_canary.compare import compare, describe_outcome, semantic_view

CASES = Path(__file__).parent / "cases"


class CompareTests(unittest.TestCase):
    def test_identical_environment_is_unchanged(self):
        artifact = capture(sys.executable, CASES / "return_value.py")

        self.assertFalse(compare(artifact, artifact)["changed"])

    def test_default_view_ignores_exception_message(self):
        baseline = capture(sys.executable, CASES / "return_value.py")
        baseline["outcome"] = {
            "kind": "exception",
            "message": "old text",
            "pydantic_error_types": None,
            "type": "builtins.ValueError",
        }
        candidate = deepcopy(baseline)
        candidate["outcome"]["message"] = "new text"

        self.assertFalse(compare(baseline, candidate)["changed"])
        self.assertTrue(compare(baseline, candidate, exact=True)["changed"])

    def test_warning_category_is_semantic(self):
        artifact = capture(sys.executable, CASES / "warning_value.py")

        self.assertEqual(
            semantic_view(artifact)["warning_categories"], ["builtins.DeprecationWarning"]
        )

    def test_return_value_change_is_semantic(self):
        baseline = capture(sys.executable, CASES / "return_value.py")
        candidate = deepcopy(baseline)
        candidate["outcome"]["value"]["answer"] = 43

        self.assertTrue(compare(baseline, candidate)["changed"])

    def test_rejects_different_case_bytes(self):
        baseline = capture(sys.executable, CASES / "return_value.py")
        candidate = deepcopy(baseline)
        candidate["case"]["sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "different case bytes"):
            compare(baseline, candidate)

    def test_reports_changed_batch_input(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "evals_inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["outcome"]["items"][1]["outcome"]["value"]["answer"] = 2

        report = compare(baseline, candidate)

        self.assertTrue(report["changed"])
        self.assertEqual(report["batch"]["total"], 2)
        self.assertEqual(report["batch"]["changes"][0]["name"], "zero")

    def test_batch_default_view_ignores_exception_message(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        baseline["outcome"]["items"][0]["outcome"] = {
            "kind": "exception",
            "message": "old text",
            "pydantic_error_types": None,
            "type": "builtins.ValueError",
        }
        candidate = deepcopy(baseline)
        candidate["outcome"]["items"][0]["outcome"]["message"] = "new text"

        self.assertFalse(compare(baseline, candidate)["changed"])
        self.assertTrue(compare(baseline, candidate, exact=True)["changed"])

    def test_rejects_different_input_bytes(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["inputs"]["sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "different input bytes"):
            compare(baseline, candidate)

    def test_rejects_different_batch_counts(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["outcome"]["items"].pop()

        with self.assertRaisesRegex(ValueError, "different input counts"):
            compare(baseline, candidate)

    def test_rejects_different_batch_identities(self):
        baseline = capture(
            sys.executable,
            CASES / "input_value.py",
            inputs=CASES / "inputs.json",
        )
        candidate = deepcopy(baseline)
        candidate["outcome"]["items"][0]["name"] = "different"

        with self.assertRaisesRegex(ValueError, "different input identities"):
            compare(baseline, candidate)

    def test_pydantic_error_types_are_the_semantic_exception_identity(self):
        artifact = capture(sys.executable, CASES / "return_value.py")
        artifact["outcome"] = {
            "kind": "exception",
            "message": "unstable detail",
            "pydantic_error_types": ["greater_than", "missing"],
            "type": "pydantic_core.ValidationError",
        }

        self.assertEqual(
            semantic_view(artifact)["outcome"],
            {"kind": "exception", "pydantic_error_types": ["greater_than", "missing"]},
        )

    def test_describe_outcome_covers_public_summary_shapes(self):
        long_value = "x" * 130
        outcomes = [
            ({"kind": "return", "value": long_value}, "return ", "..."),
            ({"kind": "batch", "items": [{}, {}]}, "batch[2]", "batch[2]"),
            (
                {"kind": "exception", "pydantic_error_types": ["missing", "int_type"]},
                "ValidationError[missing,int_type]",
                "ValidationError[missing,int_type]",
            ),
            (
                {"kind": "exception", "pydantic_error_types": None, "type": "builtins.ValueError"},
                "exception builtins.ValueError",
                "exception builtins.ValueError",
            ),
        ]

        for outcome, prefix, suffix in outcomes:
            with self.subTest(outcome=outcome):
                rendered = describe_outcome(outcome)
                self.assertTrue(rendered.startswith(prefix))
                self.assertTrue(rendered.endswith(suffix))


if __name__ == "__main__":
    unittest.main()
