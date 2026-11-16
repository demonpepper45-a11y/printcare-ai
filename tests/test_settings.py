import tempfile
import unittest
from pathlib import Path

from printcare.settings import ConfigError, Settings, resolve_model_api_key


class SettingsTest(unittest.TestCase):
    def test_defaults_without_environment_variables(self):
        settings = Settings.from_env({})

        self.assertEqual(settings.environment, "local")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.data_dir, Path("runtime"))
        self.assertEqual(settings.database_path, Path("runtime/printcare.sqlite3"))
        self.assertIsNone(settings.model_api_key)
        self.assertIsNone(settings.model_base_url)
        self.assertEqual(settings.model_name, "deepseek-flash")
        self.assertIsNone(settings.model_api_key_file)

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

    def test_model_name_and_key_file_from_env(self):
        settings = Settings.from_env(
            {
                "PRINTCARE_MODEL_NAME": "deepseek-v4-pro",
                "PRINTCARE_MODEL_API_KEY_FILE": "runtime/key.txt",
            }
        )

        self.assertEqual(settings.model_name, "deepseek-v4-pro")
        self.assertEqual(settings.model_api_key_file, Path("runtime/key.txt"))

    def test_admin_token_from_env(self):
        self.assertIsNone(Settings.from_env({}).admin_token)
        self.assertEqual(
            Settings.from_env({"PRINTCARE_ADMIN_TOKEN": "secret"}).admin_token,
            "secret",
        )


class ResolveModelKeyTest(unittest.TestCase):
    def test_environment_key_wins(self):
        settings = Settings.from_env({"PRINTCARE_MODEL_API_KEY": "sk-env"})

        self.assertEqual(resolve_model_api_key(settings), "sk-env")

    def test_explicit_key_file_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "key.txt"
            key_file.write_text("sk-file\n", encoding="utf-8")
            settings = Settings.from_env({"PRINTCARE_MODEL_API_KEY_FILE": str(key_file)})

            self.assertEqual(resolve_model_api_key(settings), "sk-file")

    def test_missing_key_raises_with_helpful_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env({})

            with self.assertRaises(ConfigError) as caught:
                resolve_model_api_key(settings, default_file=Path(tmp) / "missing.txt")

        self.assertIn("runtime/model_key.txt", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
