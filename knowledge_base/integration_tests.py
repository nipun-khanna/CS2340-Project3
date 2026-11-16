"""PostgreSQL integration tests. Run explicitly when DATABASE_URL points to a test-capable server."""

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from knowledge_base.models import Document, DocumentChunk
from knowledge_base.services.ingestion import discover_pdfs, ingest_file
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


class KnowledgeBaseMaintenanceTests(TestCase):
    def setUp(self):
        self.pdf = SimpleNamespace(pages=[(1, "Dehydration can cause thirst and dizziness.")],
                                   page_count=1, title="Fixture title", publisher="Fixture publisher", sparse_pages=[])
        patches = [patch("knowledge_base.services.ingestion.extract_pdf", return_value=self.pdf),
                   patch("knowledge_base.services.ingestion.embed_text", return_value=VECTOR)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_command(self, *args, **kwargs):
        out, err = StringIO(), StringIO()
        call_command(*args, stdout=out, stderr=err, **kwargs)
        return out.getvalue() + err.getvalue()

    def test_force_reprocesses_unchanged_document(self):
        path = next(Path(settings.DATA_DIR).glob("*.pdf"))
        _, document, _ = ingest_file(path)
        old_chunk = document.chunks.get().pk
        self.assertEqual(ingest_file(path)[0], "skipped")
        self.assertEqual(ingest_file(path, force=True)[0], "processed")
        self.assertNotEqual(document.chunks.get().pk, old_chunk)

    def test_clear_removes_everything_only_after_confirmation(self):
        self.assertIn("already empty", self.run_command("clear_knowledge_base"))
        for path in sorted(Path(settings.DATA_DIR).glob("*.pdf"))[:2]:
            ingest_file(path)
        with patch("builtins.input", return_value="no"):
            self.assertIn("Cancelled", self.run_command("clear_knowledge_base"))
        self.assertEqual((Document.objects.count(), DocumentChunk.objects.count()), (2, 2))
        with patch("builtins.input", return_value="yes"):
            self.assertIn("Removed 2 documents and 2 chunks", self.run_command("clear_knowledge_base"))
        self.assertEqual((Document.objects.count(), DocumentChunk.objects.count()), (0, 0))
        for path in sorted(Path(settings.DATA_DIR).glob("*.pdf"))[:1]:
            ingest_file(path)
        self.assertIn("Removed 1 documents", self.run_command("clear_knowledge_base", yes=True))
        self.assertTrue(any(Path(settings.DATA_DIR).glob("*.pdf")), "PDFs on disk must not be touched")

    def test_reload_prunes_missing_pdfs_and_reembeds_the_rest(self):
        pdf_count = len(discover_pdfs())
        Document.objects.create(filename="gone.pdf", title="Gone", relative_path="gone.pdf",
                                status=Document.Status.COMPLETED, chunk_count=0)
        with patch("builtins.input", return_value="no"):
            self.assertIn("Cancelled", self.run_command("reload_knowledge_base"))
        self.assertTrue(Document.objects.filter(relative_path="gone.pdf").exists())
        self.assertEqual(Document.objects.count(), 1)

        output = self.run_command("reload_knowledge_base", yes=True)
        self.assertIn("Removed 1 document(s) without a PDF.", output)
        self.assertIn(f"Processed: {pdf_count}", output)
        self.assertFalse(Document.objects.filter(relative_path="gone.pdf").exists())
        self.assertEqual(Document.objects.filter(status=Document.Status.COMPLETED).count(), pdf_count)

        # Unchanged files are re-embedded on reload, not skipped, and nothing is pruned or prompted for.
        with patch("builtins.input", side_effect=AssertionError("should not prompt")):
            output = self.run_command("reload_knowledge_base")
        self.assertIn(f"Processed: {pdf_count}", output)
        self.assertIn("Skipped unchanged: 0", output)

    def test_reload_keeps_old_version_searchable_when_embedding_fails(self):
        path = next(Path(settings.DATA_DIR).glob("*.pdf"))
        _, document, _ = ingest_file(path)
        old_chunk = document.chunks.get().pk
        with patch("knowledge_base.management.commands.ingest_documents.discover_pdfs", return_value=[path]), patch(
            "knowledge_base.management.commands.reload_knowledge_base.discover_pdfs", return_value=[path]
        ), patch("knowledge_base.services.ingestion.embed_text", side_effect=RuntimeError("provider failed")):
            with self.assertRaises(CommandError):
                self.run_command("reload_knowledge_base", yes=True)
        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.COMPLETED)
        self.assertEqual(document.chunks.get().pk, old_chunk)
        self.assertIn("provider failed", document.error_message)


class AskPageTests(TestCase):
    def test_login_ask_and_logout_flow(self):
        client = Client(enforce_csrf_checks=False)
        self.assertRedirects(client.get("/"), "/accounts/login/?next=/", fetch_redirect_response=False)
        self.assertContains(client.get("/accounts/login/"), "Sign in")
        get_user_model().objects.create_user(username="resident", password="a-long-test-password")
        response = client.post("/accounts/login/", {"username": "resident", "password": "wrong", "next": "/"})
        self.assertContains(response, "didn't match")
        response = client.post("/accounts/login/", {"username": "resident", "password": "a-long-test-password", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        answer = {"question": "q", "answered": True, "answer": "Drink water [1].",
                  "sources": [{"number": 1, "document_id": 1, "title": "Hydration guide", "publisher": None, "source_url": None,
                               "page_start": 1, "page_end": 1, "chunk_id": 1, "text": "Drink water.", "similarity_score": 0.9}]}
        with patch("knowledge_base.views.answer_question", return_value=answer):
            response = client.post("/", {"question": "How do I stay hydrated?"})
        self.assertContains(response, "Drink water [1].")
        self.assertContains(response, "Hydration guide")
        self.assertRedirects(client.post("/accounts/logout/"), "/accounts/login/", fetch_redirect_response=False)
        self.assertEqual(client.get("/").status_code, 302)

    def test_ask_page_enforces_csrf(self):
        client = Client(enforce_csrf_checks=True)
        user = get_user_model().objects.create_user(username="resident", password="a-long-test-password")
        client.force_login(user)
        with patch("knowledge_base.views.answer_question") as answer:
            self.assertEqual(client.post("/", {"question": "How do I stay hydrated?"}).status_code, 403)
        answer.assert_not_called()
