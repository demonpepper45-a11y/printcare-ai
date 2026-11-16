import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from printcare.api.app import create_app
from printcare.assistant.provider import FakeProvider
from printcare.ingestion.store import IngestStore
from printcare.settings import Settings
from tests.retrieval_corpus import add_document

TEXT = "A1 热床不加热时，先断电，检查热床线缆与电源接口是否插紧。"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_page.html"


def answered_payload():
    return json.dumps(
        {
            "status": "answered",
            "answer": "先断电，再检查热床线缆。",
            "citations": [{"source": "S1", "quote": "先断电，检查热床线缆"}],
            "missing_information": [],
            "follow_up_question": None,
            "refusal_reason": None,
        },
        ensure_ascii=False,
    )


class ApiTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "api.sqlite3"
        store = IngestStore(self.db_path)
        add_document(
            store,
            locale="zh",
            path="a1/troubleshooting/heatbed",
            machines=("a1",),
            title="A1 热床不加热排查",
            texts=(TEXT,),
        )
        store.close()
        self.settings = Settings(
            environment="local",
            log_level="INFO",
            data_dir=Path(self.tmp.name),
            database_path=self.db_path,
            admin_token="test-token",
        )
        self.inventory = [
            {
                "id": 1,
                "path": "a1-mini/troubleshooting/new",
                "title": "New page",
                "updatedAt": "2026-11-10T00:00:00Z",
                "locale": "en",
            }
        ]
        self.page_html = FIXTURE.read_text(encoding="utf-8")
        self.provider = FakeProvider(
            [
                answered_payload(),
                answered_payload(),
                answered_payload(),
                answered_payload(),
            ]
        )

    def tearDown(self):
        self.tmp.cleanup()

    def make_client(self):
        app = create_app(
            db_path=self.db_path,
            provider=self.provider,
            settings=self.settings,
            inventory_fetcher=lambda: self.inventory,
            page_fetcher=lambda ref: self.page_html,
        )
        return TestClient(app)


class CoreApiTest(ApiTestBase):
    def test_health_and_machines(self):
        client = self.make_client()

        health = client.get("/api/v1/health")
        machines = client.get("/api/v1/machines")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["documents"], 1)
        self.assertEqual(health.json()["model"], "fake")
        self.assertEqual([item["code"] for item in machines.json()], ["a1", "a1_mini"])

    def test_chat_returns_answer_with_citation(self):
        client = self.make_client()

        response = client.post(
            "/api/v1/chat",
            json={"question": "A1 热床不加热怎么办？", "machine": "a1"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(len(body["citations"]), 1)
        self.assertEqual(body["citations"][0]["machine"], "a1")
        self.assertTrue(body["session_id"].startswith("s_"))
        self.assertTrue(response.headers["X-Request-Id"].startswith("req_"))

    def test_chat_validation_error_format(self):
        client = self.make_client()

        response = client.post(
            "/api/v1/chat",
            json={"question": "", "machine": "a1"},
        )

        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_failed")
        self.assertTrue(error["details"]["fields"])
        self.assertTrue(error["request_id"])

    def test_invalid_machine_is_rejected(self):
        client = self.make_client()

        response = client.post(
            "/api/v1/chat",
            json={"question": "热床不加热", "machine": "x1"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_failed")

    def test_machine_mismatch_needs_clarification(self):
        client = self.make_client()

        response = client.post(
            "/api/v1/chat",
            json={"question": "A1 mini 热床不加热怎么办？", "machine": "a1"},
        )

        body = response.json()
        self.assertEqual(body["status"], "needs_clarification")
        self.assertEqual(body["machine_check"]["result"], "mismatch")
        self.assertEqual(self.provider.calls, [])

    def test_provider_error_maps_to_source_unavailable(self):
        self.provider = FakeProvider([])
        client = self.make_client()

        response = client.post(
            "/api/v1/chat",
            json={"question": "A1 热床不加热怎么办？", "machine": "a1"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "source_unavailable")

    def test_session_lifecycle(self):
        client = self.make_client()
        created = client.post(
            "/api/v1/chat",
            json={"question": "A1 热床不加热怎么办？", "machine": "a1"},
        ).json()
        session_id = created["session_id"]

        fetched = client.get(f"/api/v1/sessions/{session_id}")
        patched = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"machine": "a1_mini", "attempted_steps": ["已断电"]},
        )
        deleted = client.delete(f"/api/v1/sessions/{session_id}")
        missing = client.get(f"/api/v1/sessions/{session_id}")

        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(patched.json()["machine"], "a1_mini")
        self.assertEqual(patched.json()["attempted_steps"], ["已断电"])
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "session_not_found")

    def test_unknown_session_returns_404(self):
        client = self.make_client()

        response = client.get("/api/v1/sessions/s_aaaaaaaaaaaaaaaa")

        self.assertEqual(response.status_code, 404)

    def test_feedback_is_recorded(self):
        client = self.make_client()

        created = client.post(
            "/api/v1/feedback",
            json={"session_id": "s_aaaaaaaaaaaaaaaa", "solved": True, "comment": "有帮助"},
        )
        summary = client.get("/api/v1/admin/feedback", headers={"X-Admin-Token": "test-token"})

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["id"], 1)
        self.assertEqual(summary.json()["total"], 1)
        self.assertEqual(summary.json()["solved"], 1)


class AdminApiTest(ApiTestBase):
    def test_documents_require_token(self):
        client = self.make_client()

        unauthorized = client.get("/api/v1/admin/documents")
        authorized = client.get("/api/v1/admin/documents", headers={"X-Admin-Token": "test-token"})

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.json()["error"]["code"], "unauthorized")
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(len(authorized.json()), 1)
        self.assertEqual(authorized.json()[0]["chunk_count"], 1)

    def test_document_can_be_disabled(self):
        client = self.make_client()
        documents = client.get(
            "/api/v1/admin/documents", headers={"X-Admin-Token": "test-token"}
        ).json()
        doc_id = documents[0]["doc_id"]

        response = client.patch(
            f"/api/v1/admin/documents/{doc_id}",
            json={"enabled": False},
            headers={"X-Admin-Token": "test-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])

    def test_unknown_document_returns_404(self):
        client = self.make_client()

        response = client.patch(
            "/api/v1/admin/documents/doc_missing",
            json={"enabled": False},
            headers={"X-Admin-Token": "test-token"},
        )

        self.assertEqual(response.status_code, 404)

    def test_refresh_ingests_from_inventory(self):
        client = self.make_client()

        response = client.post(
            "/api/v1/admin/refresh",
            json={"limit": 1},
            headers={"X-Admin-Token": "test-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["inserted"], 1)
        documents = client.get(
            "/api/v1/admin/documents", headers={"X-Admin-Token": "test-token"}
        ).json()
        self.assertEqual(len(documents), 2)


if __name__ == "__main__":
    unittest.main()
