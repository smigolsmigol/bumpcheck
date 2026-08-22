import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class RequirementIntegrationTests(unittest.TestCase):
    def assert_check(
        self,
        *,
        issue: str,
        case: str,
        baseline: str,
        candidate: str,
        expected_exit: int,
        expected_output: str,
        extra_args: tuple[str, ...] = (),
    ):
        command = [
            sys.executable,
            "-m",
            "bumpcheck",
            "check",
            str(ROOT / "examples" / "regressions" / case),
            "--baseline",
            baseline,
            "--candidate",
            candidate,
            "--python-version",
            "3.12",
            "--timeout",
            "120",
            *extra_args,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            cwd=ROOT,
            text=True,
            timeout=180,
        )

        output = completed.stderr or completed.stdout
        self.assertEqual(completed.returncode, expected_exit, f"{issue}\n{output}")
        self.assertIn(expected_output, completed.stdout, issue)

    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_pydantic_11681_detects_strict_mapping_regression(self):
        issue = "https://github.com/pydantic/pydantic/issues/11681"
        self.assert_check(
            issue=issue,
            case="strict_mapping_key.py",
            baseline="pydantic==2.10.6",
            candidate="pydantic==2.11.1",
            expected_exit=1,
            expected_output="CHANGED strict_mapping_key",
        )

    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_pydantic_12360_detects_field_info_default_regression(self):
        issue = "https://github.com/pydantic/pydantic/issues/12360"
        self.assert_check(
            issue=issue,
            case="field_info_default.py",
            baseline="pydantic==2.11.7",
            candidate="pydantic==2.12.0",
            expected_exit=1,
            expected_output="CHANGED field_info_default",
        )

    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_pydantic_12360_detects_instructor_partial_stream_regression(self):
        issue = "https://github.com/pydantic/pydantic/issues/12360"
        inputs = ROOT / "examples" / "inputs" / "instructor_stream.json"
        self.assert_check(
            issue=issue,
            case="instructor_partial_stream.py",
            baseline="pydantic==2.11.7",
            candidate="pydantic==2.12.0",
            expected_exit=1,
            expected_output="CHANGED instructor_partial_stream",
            extra_args=("--with", "instructor==1.9.2", "--inputs", str(inputs)),
        )

    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_pydantic_12379_detects_serialize_as_any_regression(self):
        issue = "https://github.com/pydantic/pydantic/issues/12379"
        self.assert_check(
            issue=issue,
            case="serialize_as_any.py",
            baseline="pydantic==2.11.9",
            candidate="pydantic==2.12.0",
            expected_exit=1,
            expected_output="CHANGED serialize_as_any",
        )

    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_pydantic_12379_accepts_fixed_serialize_as_any_release(self):
        issue = "https://github.com/pydantic/pydantic/issues/12379"
        self.assert_check(
            issue=issue,
            case="serialize_as_any.py",
            baseline="pydantic==2.11.9",
            candidate="pydantic==2.12.5",
            expected_exit=0,
            expected_output="UNCHANGED serialize_as_any",
        )


if __name__ == "__main__":
    unittest.main()
