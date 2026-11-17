import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request

from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase

from knowledge_base.services.answering import NOT_FOUND
from knowledge_base.services.evaluation import evaluate_case, load_cases
from knowledge_base.services.web_ingestion import MAX_PAGE_BYTES, TrustedRedirects, fetch_webpage, validate_source_url
from knowledge_base.views import developer_tools


class WebScrapingTests(SimpleTestCase):
    def test_rejects_untrusted_urls_and_redirects(self):
        for url in ["http://medlineplus.gov/x", "https://localhost/x", "https://127.0.0.1/x",
                    "file:///etc/passwd", "https://medlineplus.gov.evil.example/x",
                    "https://user:pass@medlineplus.gov/x", "https://medlineplus.gov:8443/x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_source_url(url)
        with self.assertRaises(ValueError):
            TrustedRedirects().redirect_request(Request("https://medlineplus.gov/x"), None,
                                                302, "Found", {}, "http://127.0.0.1/private")
        self.assertEqual(validate_source_url("https://medlineplus.gov/x#summary"), "https://medlineplus.gov/x")

    @patch("knowledge_base.services.web_ingestion.build_opener")
    def test_extracts_article_and_discards_navigation_and_scripts(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.geturl.return_value = "https://medlineplus.gov/x"
        response.headers.get_content_type.return_value = "text/html"
        response.read.return_value = b'<html><title>Hydration guide</title><body><nav>Navigation</nav><main><script>bad()</script><p>Drink water regularly. Dry mouth and dizziness can be symptoms of dehydration in adults.</p></main><footer>Footer</footer></body></html>'
        page = fetch_webpage("https://medlineplus.gov/x")
        self.assertEqual(page.title, "Hydration guide")
        self.assertIn("Dry mouth", page.pages[0][1])
        for excluded in ("Navigation", "bad()", "Footer"):
            self.assertNotIn(excluded, page.pages[0][1])
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 15)
        response.read.assert_called_once_with(MAX_PAGE_BYTES + 1)

    @patch("knowledge_base.services.web_ingestion.build_opener")
    def test_rejects_non_html_oversized_and_empty_pages(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.geturl.return_value = "https://medlineplus.gov/x"
        response.headers.get_content_type.return_value = "application/pdf"
        with self.assertRaisesRegex(ValueError, "HTML"):
            fetch_webpage("https://medlineplus.gov/x")
        response.headers.get_content_type.return_value = "text/html"
        response.read.return_value = b"x" * (MAX_PAGE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "2 MiB"):
            fetch_webpage("https://medlineplus.gov/x")
        response.read.return_value = b"<html><body>Empty</body></html>"
        with self.assertRaisesRegex(ValueError, "too little"):
            fetch_webpage("https://medlineplus.gov/x")


class EvaluationTests(SimpleTestCase):
    def setUp(self):
        self.case = load_cases()[0]
        self.good = {"answered": True, "answer": "You may be thirsty, have a dry mouth, or feel dizzy [1].",
                     "sources": [{"number": 1, "title": self.case["expected_title"], "text": "Reference passage"}]}

    @patch("knowledge_base.services.evaluation.answer_question")
    def test_pass_and_fact_source_citation_failures(self, answer):
        answer.return_value = self.good
        self.assertEqual(evaluate_case(self.case)["status"], "PASS")
        answer.return_value = {**self.good, "answer": "Thirsty [1]."}
        report = evaluate_case(self.case)
        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(report["missing_concepts"], [["dry mouth"], ["dizziness", "dizzy"]])
        answer.return_value = {**self.good, "sources": [{"number": 2, "title": "Wrong document"}]}
        report = evaluate_case(self.case)
        self.assertFalse(report["checks"]["expected_source"])
        self.assertFalse(report["checks"]["inline_citation"])

    @patch("knowledge_base.services.evaluation.answer_question")
    def test_unrelated_question_must_abstain_and_not_include_sources(self, answer):
        case = load_cases()[-1]
        answer.return_value = {"answered": False, "answer": NOT_FOUND, "sources": []}
        self.assertEqual(evaluate_case(case)["status"], "PASS")
        answer.return_value = {"answered": True, "answer": "It will rain.", "sources": []}
        self.assertEqual(evaluate_case(case)["status"], "REVIEW")

    @patch("knowledge_base.services.evaluation.answer_question", side_effect=RuntimeError("private connection string"))
    def test_provider_failure_is_an_error_not_a_pass(self, answer):
        with self.assertLogs("knowledge_base.services.evaluation", "ERROR"):
            report = evaluate_case(self.case)
        self.assertEqual(report["status"], "ERROR")
        self.assertNotIn("private", json.dumps(report))

    def test_invalid_case_files_fail_before_generation(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            for cases in [[], {}, [self.case, self.case], [{**self.case, "required_concepts": ["not a group"]}]]:
                path.write_text(json.dumps(cases))
                with self.subTest(cases=cases), self.assertRaises(ValueError):
                    load_cases(path)

    @patch("knowledge_base.management.commands.evaluate_answers.evaluate_case")
    def test_command_writes_report_and_fails_on_review_or_error(self, evaluate):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            evaluate.side_effect = [{"status": "ERROR", "elapsed_seconds": 0, "error": "Unavailable"}] + [
                {"status": "PASS", "elapsed_seconds": 0} for _ in load_cases()[1:]
            ]
            with self.assertRaises(CommandError):
                call_command("evaluate_answers", output=str(output), stdout=StringIO())
            report = json.loads(output.read_text())
            self.assertEqual(report["passed"], report["total"] - 1)
            self.assertEqual(report["results"][0]["status"], "ERROR")
            evaluate.side_effect = [{"status": "PASS", "elapsed_seconds": 0} for _ in load_cases()]
            out = StringIO()
            call_command("evaluate_answers", output=str(output), stdout=out)
            self.assertIn("Matched expectations: 6/6", out.getvalue())
            self.assertEqual(json.loads(output.read_text())["passed"], 6)


class DeveloperViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, data=None, user=None):
        request = self.factory.get("/developer/") if data is None else self.factory.post("/developer/", data)
        request.user = user or SimpleNamespace(is_authenticated=True, is_staff=True)
        return developer_tools(request)

    def test_requires_staff(self):
        self.assertEqual(self.request(user=AnonymousUser()).status_code, 302)
        self.assertEqual(self.request(user=SimpleNamespace(is_authenticated=True, is_staff=False)).status_code, 403)

    @patch("knowledge_base.models.Document.objects.order_by", return_value=[])
    def test_renders_tools_and_validates_action(self, documents):
        response = self.request()
        self.assertContains(response, "Ingest a PDF")
        self.assertContains(response, "Ingest a webpage")
        self.assertContains(response, "Test a known question")
        self.assertContains(self.request({"action": "pdf", "pdf": "../../outside.pdf"}), "Choose a PDF", status_code=400)
        self.assertContains(self.request({"action": "web", "url": "http://localhost"}), "HTTPS URL", status_code=400)
        self.assertEqual(self.request({"action": "unsupported"}).status_code, 400)

    @patch("knowledge_base.models.Document.objects.order_by", return_value=[])
    @patch("knowledge_base.views.evaluate_case")
    def test_evaluates_only_a_known_case_and_escapes_answer(self, evaluate, documents):
        evaluate.return_value = {"status": "REVIEW", "question": "q", "expected_answer": "reference",
                                 "answer": "<script>bad()</script>", "checks": {}, "elapsed_seconds": 0}
        self.assertContains(self.request({"action": "evaluate", "case_id": load_cases()[0]["id"]}), "&lt;script&gt;")
        evaluate.assert_called_once_with(load_cases()[0])
        self.assertEqual(self.request({"action": "evaluate", "case_id": "unknown"}).status_code, 400)

    @patch("knowledge_base.models.Document.objects.order_by", return_value=[])
    @patch("knowledge_base.views.call_command")
    def test_clear_and_reload_require_confirmation_and_run_commands(self, command, documents):
        self.assertContains(self.request(), "Reload knowledge base")
        self.assertContains(self.request({"action": "clear"}), "Tick the confirmation box", status_code=400)
        command.assert_not_called()

        command.side_effect = lambda name, **kw: kw["stdout"].write("Removed 12 documents and 300 chunks.\n")
        self.assertContains(self.request({"action": "clear", "confirm": "yes"}), "Removed 12 documents and 300 chunks.")
        self.assertEqual(command.call_args.args, ("clear_knowledge_base",))
        self.assertTrue(command.call_args.kwargs["yes"])

        command.side_effect = lambda name, **kw: kw["stdout"].write(
            "Found 12 PDF files.\nprocessed: Doc\nProcessed: 12\nSkipped unchanged: 0\nFailed: 0\nTotal searchable chunks: 300\n")
        response = self.request({"action": "reload", "confirm": "yes"})
        self.assertContains(response, "Processed: 12 Skipped unchanged: 0 Failed: 0 Total searchable chunks: 300")
        self.assertEqual(command.call_args.args, ("reload_knowledge_base",))

        command.side_effect = CommandError("1 document(s) failed")
        with self.assertLogs("knowledge_base.views", "ERROR"):
            self.assertEqual(self.request({"action": "reload", "confirm": "yes"}).status_code, 503)
