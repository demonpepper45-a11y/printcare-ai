import unittest

from printcare.ingestion.ids import (
    canonical_path,
    compute_chunk_id,
    compute_content_hash,
    compute_doc_id,
    normalize_whitespace,
)


class CanonicalPathTest(unittest.TestCase):
    def test_normalises_case_slashes_and_query(self):
        self.assertEqual(
            canonical_path("EN/A1-Mini//Troubleshooting/Extruder-Clog/?lang=x#top"),
            "en/a1-mini/troubleshooting/extruder-clog",
        )

    def test_decodes_percent_escapes(self):
        self.assertEqual(canonical_path("a1/heatbed%20sensor/"), "a1/heatbed sensor")


class IdentifierTest(unittest.TestCase):
    def test_doc_id_is_stable_and_locale_specific(self):
        first = compute_doc_id("zh", "a1-mini/troubleshooting/extruder-clog")
        second = compute_doc_id("zh", "a1-mini/troubleshooting/extruder-clog")
        other_locale = compute_doc_id("en", "a1-mini/troubleshooting/extruder-clog")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other_locale)
        self.assertRegex(first, r"^doc_[0-9a-f]{16}$")

    def test_chunk_id_changes_when_text_changes(self):
        doc_id = compute_doc_id("en", "a1/maintenance/belt_tension")
        first = compute_chunk_id(doc_id, "Tighten the belt.")
        second = compute_chunk_id(doc_id, "Loosen the belt.")

        self.assertRegex(first, r"^doc_[0-9a-f]{16}#[0-9a-f]{10}$")
        self.assertNotEqual(first, second)

    def test_chunk_id_ignores_whitespace_differences(self):
        doc_id = compute_doc_id("en", "a1/maintenance/belt_tension")

        self.assertEqual(
            compute_chunk_id(doc_id, "Tighten  the\nbelt."),
            compute_chunk_id(doc_id, "Tighten the belt."),
        )

    def test_content_hash_is_prefixed(self):
        digest = compute_content_hash("some text")

        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), len("sha256:") + 64)

    def test_whitespace_normalisation(self):
        self.assertEqual(normalize_whitespace(" a \n b \u00a0 c "), "a b c")


if __name__ == "__main__":
    unittest.main()
