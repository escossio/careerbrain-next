"""Single short gate shared by local runs and GitHub Actions."""

import sys
import unittest

from tools.offline import enable


def main() -> int:
    enable()
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
