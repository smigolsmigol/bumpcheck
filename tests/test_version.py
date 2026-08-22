import unittest
from importlib.metadata import version

from pydantic_canary import __version__


class VersionTests(unittest.TestCase):
    def test_runtime_version_matches_distribution_metadata(self):
        self.assertEqual(__version__, version("pydantic-canary"))


if __name__ == "__main__":
    unittest.main()
