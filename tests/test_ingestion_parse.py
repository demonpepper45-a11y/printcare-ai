import unittest
from pathlib import Path

from printcare.ingestion.models import DocumentRef, ListBlock, TableBlock
from printcare.ingestion.parse import ParseError, parse_document, render_document_text

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_page.html"
REF = DocumentRef(
    locale="en",
    path="a1-mini/troubleshooting/extruder-clog",
    title="Extruder cleaning",
    official_updated_at="2026-11-10T00:00:00Z",
)


class ParseDocumentTest(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.parsed = parse_document(self.html, REF)

    def test_headings_keep_order_and_anchors(self):
        headings = [block for block in self.parsed.blocks if block.__class__.__name__ == "Heading"]

        self.assertEqual(
            [heading.text for heading in headings],
            ["When to use", "Tools and materials", "Steps", "Torque spec"],
        )
        self.assertEqual(headings[2].anchor, "steps")

    def test_lists_and_tables_are_rendered(self):
        renders = [render_document_text([block]) for block in self.parsed.blocks]

        self.assertIn("- Tweezers\n- Brush", renders)
        self.assertIn("1. Power off the printer.\n2. Remove the hotend.", renders)
        self.assertIn("Part | Torque\nScrew A | 1.2 Nm", renders)

    def test_images_become_placeholders_and_are_collected(self):
        texts = [render_document_text([block]) for block in self.parsed.blocks]
        combined = "\n".join(texts)

        self.assertIn("[图: Step 1 photo]", combined)
        self.assertIn("[图: step2.jpg]", combined)
        chunk_images = [image for chunk in self.parsed.chunks for image in chunk.images]
        self.assertEqual(len(chunk_images), 2)
        self.assertTrue(
            all(image.src.startswith("https://wiki.bambulab.com/") for image in chunk_images)
        )

    def test_comments_and_scripts_are_ignored(self):
        text = "\n".join(chunk.text for chunk in self.parsed.chunks)

        self.assertNotIn("User comment", text)
        self.assertNotIn("tracking", text)

    def test_chunks_follow_heading_sections(self):
        paths = [chunk.heading_path for chunk in self.parsed.chunks]

        self.assertIn(("Steps", "Torque spec"), paths)
        self.assertEqual([chunk.ordinal for chunk in self.parsed.chunks], list(range(len(paths))))

    def test_chunk_ids_are_deterministic(self):
        again = parse_document(self.html, REF)

        self.assertEqual(
            [chunk.chunk_id for chunk in self.parsed.chunks],
            [chunk.chunk_id for chunk in again.chunks],
        )
        self.assertEqual(self.parsed.content_hash, again.content_hash)

    def test_content_hash_changes_when_text_changes(self):
        changed = self.html.replace("Power off the printer.", "Unplug the printer.")
        other = parse_document(changed, REF)

        self.assertNotEqual(self.parsed.content_hash, other.content_hash)

    def test_missing_contents_template_raises(self):
        with self.assertRaises(ParseError):
            parse_document("<html><body><p>none</p></body></html>", REF)

    def test_empty_template_raises(self):
        with self.assertRaises(ParseError):
            parse_document('<template slot="contents"></template>', REF)


class BlockTypeTest(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_document(FIXTURE.read_text(encoding="utf-8"), REF)

    def test_list_block_marks_ordered_and_unordered(self):
        lists = [block for block in self.parsed.blocks if isinstance(block, ListBlock)]

        self.assertEqual([block.ordered for block in lists], [False, True])
        self.assertEqual(lists[0].items, ("Tweezers", "Brush"))

    def test_table_block_keeps_rows(self):
        tables = [block for block in self.parsed.blocks if isinstance(block, TableBlock)]

        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].rows[0], ("Part", "Torque"))


class TemplateNoiseTest(unittest.TestCase):
    """Regression tests from a real page that rendered two literal "None" paragraphs."""

    HTML = (
        '<template slot="contents"><div>'
        '<h2 id="module-list">Module List</h2>'
        "<p>None</p>"
        "<p>Same paragraph.</p>"
        '<h2 id="verify">Verify</h2>'
        "<p>Same paragraph.</p>"
        "</div></template>"
    )

    def test_junk_paragraph_is_dropped(self):
        parsed = parse_document(self.HTML, REF)

        self.assertNotIn("None", [chunk.text for chunk in parsed.chunks])

    def test_identical_chunks_are_deduplicated(self):
        parsed = parse_document(self.HTML, REF)

        chunk_ids = [chunk.chunk_id for chunk in parsed.chunks]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))
        self.assertEqual([chunk.text for chunk in parsed.chunks], ["Same paragraph."])


if __name__ == "__main__":
    unittest.main()
