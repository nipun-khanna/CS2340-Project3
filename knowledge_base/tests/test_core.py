from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf
from django.test import RequestFactory, SimpleTestCase
from django.contrib.auth.models import AnonymousUser

from knowledge_base.services.chunker import chunk_pages
from knowledge_base.services.embeddings import embed_text
from knowledge_base.services.pdf_extractor import extract_pdf
from knowledge_base.services.text_cleaner import clean_text
from knowledge_base.services.retrieval import retrieve_passages
from knowledge_base.views import retrieve


class ProcessingTests(SimpleTestCase):
    def test_pdf_text_and_page_numbers(self):
        original_open = pymupdf.open
        pdf = original_open()
        pdf.new_page().insert_text((72, 72), "Take medicine as directed.")
        pdf.new_page().insert_text((72, 72), "Stay hydrated on hot days.")
        data = pdf.tobytes()
        pdf.close()
        with patch("knowledge_base.services.pdf_extractor.pymupdf.open", side_effect=lambda _: original_open(stream=data, filetype="pdf")):
            extracted = extract_pdf("sample.pdf")
        self.assertEqual(extracted.page_count, 2)
        self.assertIn("medicine", extracted.pages[0][1])
        self.assertEqual(extracted.pages[1][0], 2)

    def test_empty_pdf_rejected(self):
        original_open = pymupdf.open
        pdf = original_open()
        pdf.new_page()
        data = pdf.tobytes()
        pdf.close()
        with patch("knowledge_base.services.pdf_extractor.pymupdf.open", side_effect=lambda _: original_open(stream=data, filetype="pdf")):
            with self.assertRaisesRegex(ValueError, "No selectable text"):
                extract_pdf("empty.pdf")

    def test_cleaning_preserves_medical_values(self):
        self.assertEqual(clean_text("Take  5 mg\n daily.\n\n\nCall 911!"), "Take 5 mg daily.\n\nCall 911!")
        self.assertEqual(clean_text("anti-\ninflammatory"), "anti-inflammatory")

    def test_chunking_boundaries_and_overlap(self):
        text = " ".join(f"word{i}" for i in range(25))
        chunks = chunk_pages([(1, text), (2, "Next page text")], target=10, overlap=2)
        self.assertTrue(all(len(c.text.split()) <= 10 for c in chunks))
        self.assertEqual(chunks[0].text.split()[-2:], chunks[1].text.split()[:2])
        self.assertEqual(chunks[-1].page_start, 2)
        self.assertEqual(chunk_pages([(1, "  ")]), [])

    def test_long_input_is_bounded(self):
        chunks = chunk_pages([(3, " ".join(["health"] * 1000))])
        self.assertTrue(chunks)
        self.assertTrue(all(len(c.text.split()) <= 400 and c.page_end == 3 for c in chunks))


class EmbeddingTests(SimpleTestCase):
    def test_normalized_768_vector(self):
        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[3.0] + [0.0] * 767)])
        values = embed_text("question", "RETRIEVAL_QUERY", client=client)
        self.assertEqual(len(values), 768)
        self.assertEqual(values[0], 1.0)
        config = client.models.embed_content.call_args.kwargs["config"]
        self.assertEqual(config.output_dimensionality, 768)
        self.assertEqual(config.task_type, "RETRIEVAL_QUERY")

    def test_invalid_dimensions_rejected(self):
        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0])])
        with self.assertRaisesRegex(ValueError, "invalid dimensions"):
            embed_text("question", "RETRIEVAL_QUERY", client=client)


class RetrievalAndAPITests(SimpleTestCase):
    def test_retrieval_validates_inputs(self):
        for question, top_k in [("", 5), ("x" * 1001, 5), ("hello", 0), ("hello", True)]:
            with self.assertRaises(ValueError):
                retrieve_passages(question, top_k)

    def test_unauthenticated_and_invalid_api_requests(self):
        factory = RequestFactory()
        request = factory.post("/api/retrieve/", '{"question":"Hi"}', content_type="application/json")
        request.user = AnonymousUser()
        self.assertEqual(retrieve(request).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_staff=True)
        bad = factory.post("/api/retrieve/", '{bad', content_type="application/json")
        bad.user = request.user
        self.assertEqual(retrieve(bad).status_code, 400)
        with patch("knowledge_base.views.retrieve_passages", return_value={"question": "Hi", "results": []}):
            self.assertEqual(retrieve(request).status_code, 200)
