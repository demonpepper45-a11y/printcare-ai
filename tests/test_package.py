import unittest

import printcare
from printcare import settings


class PackageTest(unittest.TestCase):
    def test_version_is_declared(self):
        self.assertRegex(printcare.__version__, r"^\d+\.\d+\.\d+$")

    def test_settings_module_is_importable(self):
        self.assertTrue(callable(settings.Settings.from_env))


if __name__ == "__main__":
    unittest.main()
