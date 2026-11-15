import unittest

from printcare.retrieval.tokenize import (
    detect_machines,
    detect_unsupported_models,
    extract_hms_codes,
    normalize_hms,
    tokenize,
)


class TokenizeTest(unittest.TestCase):
    def test_chinese_uses_character_bigrams(self):
        self.assertEqual(tokenize("热床不加热"), ("热床", "床不", "不加", "加热"))

    def test_single_character_run_is_kept(self):
        self.assertEqual(tokenize("轴"), ("轴",))

    def test_mixed_language_keeps_ascii_words(self):
        self.assertEqual(tokenize("A1 mini 热床"), ("热床", "a1", "mini"))

    def test_hms_code_becomes_normalised_token(self):
        tokens = tokenize("HMS_0300-1800-0001-0001 传感器异常")

        self.assertIn("hms:0300_1800_0001_0001", tokens)


class HmsTest(unittest.TestCase):
    def test_normalises_separators_and_case(self):
        self.assertEqual(normalize_hms("hms_0300-1800-0001-0001"), "0300_1800_0001_0001")

    def test_extracts_code_from_title_prefix(self):
        self.assertEqual(
            extract_hms_codes("HMS_0300-1800-0001-0001: sensor abnormal"),
            ("0300_1800_0001_0001",),
        )

    def test_ignores_short_number_groups(self):
        self.assertEqual(extract_hms_codes("打印 300 秒后"), ())


class MachineDetectionTest(unittest.TestCase):
    def test_detects_a1_mini(self):
        self.assertEqual(detect_machines("A1 mini 挤出机堵料"), ("a1_mini",))
        self.assertEqual(detect_machines("a1mini 堵料"), ("a1_mini",))

    def test_detects_plain_a1(self):
        self.assertEqual(detect_machines("A1 热床不加热"), ("a1",))

    def test_ignores_model_like_text(self):
        self.assertEqual(detect_machines("打印 A1 尺寸的模型"), ("a1",))

    def test_detects_unsupported_models(self):
        self.assertEqual(detect_unsupported_models("X1C 热床"), ("x1c",))
        self.assertEqual(detect_unsupported_models("P1S 挤出机"), ("p1s",))
        self.assertEqual(detect_unsupported_models("A1 热床"), ())


if __name__ == "__main__":
    unittest.main()
