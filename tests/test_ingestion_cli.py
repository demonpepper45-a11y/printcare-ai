import tempfile
import unittest
from pathlib import Path

from printcare.ingestion.__main__ import _read_paths


class ReadPathsTest(unittest.TestCase):
    def test_skips_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paths.txt"
            path.write_text("# comment\na1/maintenance/heatbed\n\n  a1-mini/troubleshooting/x  \n")

            self.assertEqual(
                _read_paths(path),
                {"a1/maintenance/heatbed", "a1-mini/troubleshooting/x"},
            )

    def test_tolerates_utf8_bom_from_windows_editors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paths.txt"
            path.write_text("\ufeffa1-mini/troubleshooting/extruder-clog\n", encoding="utf-8")

            self.assertEqual(
                _read_paths(path),
                {"a1-mini/troubleshooting/extruder-clog"},
            )

    def test_normalises_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paths.txt"
            path.write_text("A1-Mini/Troubleshooting/Extruder-Clog\n")

            self.assertEqual(
                _read_paths(path),
                {"a1-mini/troubleshooting/extruder-clog"},
            )


if __name__ == "__main__":
    unittest.main()
