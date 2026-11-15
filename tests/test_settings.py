import unittest
from pathlib import Path

from printcare.settings import ConfigError, Settings


class SettingsTest(unittest.TestCase):
    def test_defaults_without_environment_variables(self):
        settings = Settings.from_env({})

        self.assertEqual(settings.environment, "local")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.data_dir, Path("runtime"))
        self.assertEqual(settings.database_path, Path("runtime/printcare.sqlite3"))
        self.assertIsNone(settings.model_api_key)
        self.assertIsNone(settings.model_base_url)

    def test_environment_variables_override_defaults(self):
        settings = Settings.from_env(
            {
                "PRINTCARE_ENVIRONMENT": "test",
                "PRINTCARE_LOG_LEVEL": "debug",
                "PRINTCARE_DATA_DIR": "tmp/data",
                "PRINTCARE_DATABASE_PATH": "tmp/printcare.sqlite3",
                "PRINTCARE_MODEL_BASE_URL": "https://example.invalid/v1",
            }
        )

        self.assertEqual(settings.environment, "test")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.data_dir, Path("tmp/data"))
        self.assertEqual(settings.database_path, Path("tmp/printcare.sqlite3"))
        self.assertEqual(settings.model_base_url, "https://example.invalid/v1")

    def test_database_path_defaults_below_data_dir(self):
        settings = Settings.from_env({"PRINTCARE_DATA_DIR": "tmp/knowledge"})

        self.assertEqual(settings.database_path, Path("tmp/knowledge/printcare.sqlite3"))

    def test_invalid_log_level_is_rejected_without_echoing_the_value(self):
        with self.assertRaises(ConfigError) as caught:
            Settings.from_env({"PRINTCARE_LOG_LEVEL": "verbose"})

        message = str(caught.exception)
        self.assertIn("PRINTCARE_LOG_LEVEL", message)
        self.assertNotIn("verbose", message)

    def test_describe_does_not_expose_api_key(self):
        settings = Settings.from_env({"PRINTCARE_MODEL_API_KEY": "sk-test-placeholder"})

        described = settings.describe()

        self.assertTrue(described["model_api_key_present"])
        self.assertNotIn("sk-test-placeholder", repr(described))


if __name__ == "__main__":
    unittest.main()
