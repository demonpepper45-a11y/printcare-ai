import json
import unittest

from printcare.ingestion.inventory import InventoryError, fetch_inventory, select_refs

PAGES = [
    {
        "id": 1,
        "path": "a1-mini/maintenance/belt_tension",
        "title": "A1 mini Belt Tensioning",
        "updatedAt": "2026-11-10T00:00:00Z",
        "locale": "en",
    },
    {
        "id": 2,
        "path": "A1-mini/maintenance/belt_tension",
        "title": "Duplicate casing",
        "updatedAt": "2026-11-11T00:00:00Z",
        "locale": "en",
    },
    {
        "id": 3,
        "path": "a1/maintenance/heatbed",
        "title": "A1 Heatbed Replacement",
        "updatedAt": "2026-10-14T00:00:00Z",
        "locale": "zh",
    },
    {
        "id": 4,
        "path": "x1/troubleshooting/nozzle",
        "title": "X1 page",
        "updatedAt": "2026-01-01T00:00:00Z",
        "locale": "en",
    },
    {
        "id": 5,
        "path": "a1/maintenance/heatbed",
        "title": "A1 Heatbed DE",
        "updatedAt": "2026-01-01T00:00:00Z",
        "locale": "de",
    },
]


class SelectRefsTest(unittest.TestCase):
    def test_keeps_a1_family_and_supported_locales(self):
        refs = select_refs(PAGES)

        self.assertEqual(
            [(ref.locale, ref.path) for ref in refs],
            [
                ("en", "a1-mini/maintenance/belt_tension"),
                ("zh", "a1/maintenance/heatbed"),
            ],
        )

    def test_case_variants_collapse_to_newest_update(self):
        refs = select_refs(PAGES)
        mini = [ref for ref in refs if ref.machine == "a1_mini"][0]

        self.assertEqual(mini.title, "Duplicate casing")
        self.assertEqual(mini.official_updated_at, "2026-11-11T00:00:00Z")

    def test_ref_properties(self):
        refs = select_refs(PAGES)
        heatbed = [ref for ref in refs if ref.machine == "a1"][0]

        self.assertEqual(heatbed.section, "maintenance")
        self.assertEqual(heatbed.source_url, "https://wiki.bambulab.com/zh/a1/maintenance/heatbed")

    def test_machine_filter(self):
        refs = select_refs(PAGES, machines=("a1",))

        self.assertEqual({ref.machine for ref in refs}, {"a1"})

    def test_locale_filter(self):
        refs = select_refs(PAGES, locales=("zh",))

        self.assertEqual({ref.locale for ref in refs}, {"zh"})


class FetchInventoryTest(unittest.TestCase):
    def test_decodes_pages_list(self):
        payload = {"data": {"pages": {"list": PAGES}}}

        def fake_post(_url, _payload, _timeout):
            return json.dumps(payload).encode("utf-8")

        self.assertEqual(len(fetch_inventory(fake_post)), len(PAGES))

    def test_graphql_errors_raise(self):
        def fake_post(_url, _payload, _timeout):
            return json.dumps({"errors": [{"message": "forbidden"}]}).encode("utf-8")

        with self.assertRaises(InventoryError):
            fetch_inventory(fake_post)

    def test_invalid_json_raises(self):
        def fake_post(_url, _payload, _timeout):
            return b"<html>not json</html>"

        with self.assertRaises(InventoryError):
            fetch_inventory(fake_post, retry_delay=0)

    def test_truncated_response_is_retried(self):
        payload = {"data": {"pages": {"list": PAGES}}}
        full = json.dumps(payload).encode("utf-8")
        calls = {"count": 0}

        def flaky_post(_url, _payload, _timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                return full[: len(full) // 2]
            return full

        pages = fetch_inventory(flaky_post, retry_delay=0)

        self.assertEqual(calls["count"], 2)
        self.assertEqual(len(pages), len(PAGES))

    def test_missing_list_raises(self):
        def fake_post(_url, _payload, _timeout):
            return json.dumps({"data": {"pages": {}}}).encode("utf-8")

        with self.assertRaises(InventoryError):
            fetch_inventory(fake_post)


if __name__ == "__main__":
    unittest.main()
