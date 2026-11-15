"""仓库卫生检查：配置示例不含真实密钥，敏感运行产物保持忽略。"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME_HINTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
SECRET_VALUE_PATTERN = re.compile(r"(?:sk|ghp|xox[baprs])-[A-Za-z0-9_\-]{16,}")
REQUIRED_IGNORE_ENTRIES = (".env", ".venv", "runtime/", "*.sqlite3", "chroma_db/")


class ConfigExampleTest(unittest.TestCase):
    def test_example_file_exists_and_keeps_secrets_as_placeholders(self):
        lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            value = value.strip()
            if any(hint in name.upper() for hint in SECRET_NAME_HINTS):
                self.assertTrue(
                    value == "" or value.startswith("<"),
                    f"{name.strip()} 必须留空或使用占位符，不能写入真实值",
                )

    def test_example_file_contains_no_real_looking_secret(self):
        content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIsNone(SECRET_VALUE_PATTERN.search(content))


class GitIgnoreTest(unittest.TestCase):
    def test_sensitive_artifacts_stay_ignored(self):
        entries = {
            line.strip()
            for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        for entry in REQUIRED_IGNORE_ENTRIES:
            self.assertIn(entry, entries)


if __name__ == "__main__":
    unittest.main()
