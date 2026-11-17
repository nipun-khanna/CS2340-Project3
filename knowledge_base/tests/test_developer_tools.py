import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase

from knowledge_base.services.answering import NOT_FOUND
from knowledge_base.services.evaluation import evaluate_case, load_cases
from knowledge_base.views import developer_tools


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

    def test_renders_tools_and_validates_action(self):
        response = self.request()
        self.assertContains(response, "Test a known question")
        self.assertEqual(self.request({"action": "unsupported"}).status_code, 400)

    @patch("knowledge_base.views.evaluate_case")
    def test_evaluates_only_a_known_case_and_escapes_answer(self, evaluate):
        evaluate.return_value = {"status": "REVIEW", "question": "q", "expected_answer": "reference",
                                 "answer": "<script>bad()</script>", "checks": {}, "elapsed_seconds": 0}
        self.assertContains(self.request({"action": "evaluate", "case_id": load_cases()[0]["id"]}), "&lt;script&gt;")
        evaluate.assert_called_once_with(load_cases()[0])
        self.assertEqual(self.request({"action": "evaluate", "case_id": "unknown"}).status_code, 400)
