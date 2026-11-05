"""PostgreSQL integration tests. Run explicitly when DATABASE_URL points to a test-capable server."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from knowledge_base.models import Document, DocumentChunk
from knowledge_base.services.ingestion import ingest_file
from knowledge_base.services.retrieval import retrieve_passages


VECTOR = [1.0] + [0.0] * 767
OTHER_VECTOR = [0.0, 1.0] + [0.0] * 766


class IngestionIntegrationTests(TestCase):
    def setUp(self):
        self.path = next(Path(settings.DATA_DIR).glob("*.pdf"))
        self.pdf = SimpleNamespace(pages=[(1, "Dehydration can cause thirst and dizziness.")],
                                   page_count=1, title="Fixture title", publisher="Fixture publisher", sparse_pages=[])

    def test_add_skip_replace_failure_and_cascade(self):
        with patch("knowledge_base.services.ingestion.extract_pdf", return_value=self.pdf), patch(
            "knowledge_base.services.ingestion.embed_text", return_value=VECTOR
        ):
            outcome, document, _ = ingest_file(self.path)
            self.assertEqual(outcome, "processed")
            self.assertEqual(ingest_file(self.path)[0], "skipped")
            self.assertEqual(Document.objects.count(), 1)
            old_chunk_id = document.chunks.get().pk
            self.pdf.pages = [(1, "Updated content about hydration.")]
            with patch("knowledge_base.services.ingestion.hashlib.sha256") as sha:
                sha.return_value.hexdigest.return_value = "a" * 64
                self.assertEqual(ingest_file(self.path)[0], "processed")
            document.refresh_from_db()
            new_chunk_id = document.chunks.get().pk
            self.assertNotEqual(old_chunk_id, new_chunk_id)
            with patch("knowledge_base.services.ingestion.hashlib.sha256") as sha, patch(
                "knowledge_base.services.ingestion.embed_text", side_effect=RuntimeError("provider failed")
            ):
                sha.return_value.hexdigest.return_value = "b" * 64
                with self.assertRaises(RuntimeError):
                    ingest_file(self.path)
            document.refresh_from_db()
            self.assertEqual(document.status, Document.Status.COMPLETED)
            self.assertEqual(document.chunks.get().pk, new_chunk_id)
            document.delete()
            self.assertFalse(DocumentChunk.objects.filter(pk=new_chunk_id).exists())


class RetrievalIntegrationTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(filename="fixture.pdf", title="Fixture", relative_path="fixture.pdf",
                                                status=Document.Status.COMPLETED, chunk_count=2)
        DocumentChunk.objects.create(document=self.document, text="Relevant hydration advice", chunk_index=0,
                                     page_start=2, page_end=2, embedding=VECTOR)
        DocumentChunk.objects.create(document=self.document, text="Unrelated passage", chunk_index=1,
                                     page_start=3, page_end=3, embedding=OTHER_VECTOR)

    def test_ranked_results_metadata_and_no_match(self):
        with patch("knowledge_base.services.retrieval.embed_text", return_value=VECTOR):
            result = retrieve_passages("How to hydrate?", 5)
            self.assertEqual(len(result["results"]), 1)
            self.assertEqual(result["results"][0]["title"], "Fixture")
            self.assertEqual(result["results"][0]["page_start"], 2)
        with patch("knowledge_base.services.retrieval.embed_text", return_value=[0.0, 0.0, 1.0] + [0.0] * 765):
            self.assertEqual(retrieve_passages("Unrelated question")["results"], [])

    def test_api_requires_staff_session_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        payload = json.dumps({"question": "How to hydrate?"})
        self.assertEqual(client.post("/api/retrieve/", payload, content_type="application/json").status_code, 403)
        user = get_user_model().objects.create_user(username="dev", password="a-long-test-password", is_staff=True)
        client.force_login(user)
        self.assertEqual(client.post("/api/retrieve/", payload, content_type="application/json").status_code, 403)
        with patch("knowledge_base.views.retrieve_passages", return_value={"question": "How to hydrate?", "results": []}):
            client.cookies[settings.CSRF_COOKIE_NAME] = "x" * 32
            self.assertEqual(client.post("/api/retrieve/", payload, content_type="application/json",
                                         HTTP_X_CSRFTOKEN="x" * 32).status_code, 200)
