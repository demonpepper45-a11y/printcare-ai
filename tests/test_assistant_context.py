import unittest

from printcare.assistant.context import (
    ModelOutputError,
    build_sources,
    parse_model_payload,
    select_sources,
    validate_citations,
    validate_citations_with_audit,
)
from printcare.retrieval.models import RetrievalHit

TEXT = "A1 热床不加热时，先断电，检查热床线缆与电源接口是否插紧。"


def make_hit(chunk_id="doc_1#aaa", text=TEXT, title="A1 热床不加热排查", doc_id="doc_1"):
    return RetrievalHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        score=1.0,
        text=text,
        heading_path=("故障原因",),
        anchor="cause",
        source_url="https://wiki.bambulab.com/zh/a1/troubleshooting/heatbed-not-heat-up",
        title=title,
        machines=("a1",),
        section="troubleshooting",
        official_updated_at="2026-11-10T00:00:00Z",
    )


class ParsePayloadTest(unittest.TestCase):
    def test_parses_json_object(self):
        self.assertEqual(parse_model_payload('{"status": "answered"}'), {"status": "answered"})

    def test_parses_fenced_json(self):
        self.assertEqual(
            parse_model_payload('```json\n{"status": "refused"}\n```'),
            {"status": "refused"},
        )

    def test_rejects_non_json(self):
        with self.assertRaises(ModelOutputError):
            parse_model_payload("当然可以，先断电。")

    def test_rejects_json_array(self):
        with self.assertRaises(ModelOutputError):
            parse_model_payload("[]")


class SelectSourcesTest(unittest.TestCase):
    def test_caps_chunks_per_document_but_keeps_order(self):
        hits = [make_hit(chunk_id=f"doc_a#{index}", doc_id="doc_a") for index in range(4)]
        hits += [make_hit(chunk_id="doc_b#1", doc_id="doc_b")]

        selected = select_sources(hits, max_per_doc=2)

        self.assertEqual([hit.chunk_id for hit in selected], ["doc_a#0", "doc_a#1", "doc_b#1"])


class ValidateCitationsTest(unittest.TestCase):
    def setUp(self):
        self.sources = build_sources((make_hit(),))

    def test_accepts_verbatim_quote(self):
        citations, dropped = validate_citations(
            [{"source": "S1", "quote": "先断电，检查热床线缆"}], self.sources, machine="a1"
        )

        self.assertEqual(dropped, 0)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].chunk_id, "doc_1#aaa")
        self.assertEqual(citations[0].machine, "a1")
        self.assertFalse(citations[0].quote_truncated)
        self.assertEqual(citations[0].source_url, make_hit().source_url)

    def test_rejects_unknown_source(self):
        citations, dropped = validate_citations(
            [{"source": "S9", "quote": "先断电"}], self.sources, machine="a1"
        )

        self.assertEqual(citations, ())
        self.assertEqual(dropped, 1)

    def test_rejects_non_verbatim_quote(self):
        citations, dropped = validate_citations(
            [{"source": "S1", "quote": "先拔掉电源再拆机"}], self.sources, machine="a1"
        )

        self.assertEqual(citations, ())
        self.assertEqual(dropped, 1)

    def test_truncates_long_quote(self):
        long_text = TEXT * 20
        sources = build_sources((make_hit(text=long_text),))

        citations, _ = validate_citations(
            [{"source": "S1", "quote": long_text}], sources, machine="a1"
        )

        self.assertEqual(len(citations), 1)
        self.assertTrue(citations[0].quote_truncated)
        self.assertEqual(len(citations[0].quote), 200)

    def test_accepts_visible_official_title_as_quote(self):
        hit = make_hit(title="HMS code: motor stuck", text="Equivalent codes: 123")
        citations, dropped = validate_citations(
            [{"source": "S1", "quote": "motor stuck"}], build_sources((hit,)), machine="a1"
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(len(citations), 1)

    def test_rejects_quote_outside_visible_context(self):
        sources = build_sources((make_hit(text="x" * 1200 + "hidden repair procedure"),))
        citations, dropped = validate_citations(
            [{"source": "S1", "quote": "hidden repair procedure"}], sources, machine="a1"
        )
        self.assertEqual(citations, ())
        self.assertEqual(dropped, 1)

    def test_deduplicates_same_chunk(self):
        citations, _ = validate_citations(
            [
                {"source": "S1", "quote": "先断电"},
                {"source": "S1", "quote": "检查热床线缆"},
            ],
            self.sources,
            machine="a1",
        )

        self.assertEqual(len(citations), 1)


class CitationAuditTest(unittest.TestCase):
    def setUp(self):
        self.sources = build_sources((make_hit(),))

    def test_reports_unknown_source(self):
        _, drops = validate_citations_with_audit(
            [{"source": "S9", "quote": "先断电"}], self.sources, machine="a1"
        )
        self.assertEqual([drop.reason for drop in drops], ["unknown_source"])

    def test_reports_empty_quote(self):
        _, drops = validate_citations_with_audit(
            [{"source": "S1", "quote": "  "}], self.sources, machine="a1"
        )
        self.assertEqual([drop.reason for drop in drops], ["empty_quote"])

    def test_reports_quote_not_found(self):
        _, drops = validate_citations_with_audit(
            [{"source": "S1", "quote": "先拆机再接线"}], self.sources, machine="a1"
        )
        self.assertEqual([drop.reason for drop in drops], ["quote_not_found"])
        self.assertEqual(drops[0].quote_length, len("先拆机再接线"))

    def test_reports_duplicate_source(self):
        _, drops = validate_citations_with_audit(
            [
                {"source": "S1", "quote": "先断电"},
                {"source": "S1", "quote": "检查热床线缆"},
            ],
            self.sources,
            machine="a1",
        )
        self.assertEqual([drop.reason for drop in drops], ["duplicate_source"])

    def test_reports_invalid_item(self):
        _, drops = validate_citations_with_audit(["S1"], self.sources, machine="a1")
        self.assertEqual([drop.reason for drop in drops], ["invalid_item"])

    def test_truncation_is_not_a_drop(self):
        long_text = TEXT * 20
        sources = build_sources((make_hit(text=long_text),))
        citations, drops = validate_citations_with_audit(
            [{"source": "S1", "quote": long_text}], sources, machine="a1"
        )
        self.assertEqual(drops, ())
        self.assertTrue(citations[0].quote_truncated)


if __name__ == "__main__":
    unittest.main()
