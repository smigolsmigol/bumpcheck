import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class RequirementIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("BUMPCHECK_INTEGRATION") == "1", "integration only")
    def test_detects_known_pydantic_regression(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "bumpcheck",
                "check",
                str(ROOT / "examples" / "regressions" / "strict_mapping_key.py"),
                "--baseline",
                "pydantic==2.10.6",
                "--candidate",
                "pydantic==2.11.1",
                "--with",
                ".",
                "--python-version",
                "3.12",
                "--timeout",
                "120",
            ],
            capture_output=True,
            check=False,
            cwd=ROOT,
            text=True,
            timeout=180,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr or completed.stdout)
        self.assertIn("CHANGED strict_mapping_key", completed.stdout)


if __name__ == "__main__":
    unittest.main()
