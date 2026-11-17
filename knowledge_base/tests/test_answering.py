import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, SimpleTestCase, override_settings
from google.genai import errors

from knowledge_base.services.answering import NOT_FOUND, ModelAnswer, answer_question
from knowledge_base.views import ask


def passage(number, **overrides):
    data = {
        "document_id": number, "title": f"Doc {number}", "publisher": f"Publisher {number}",
        "source_url": f"https://example.org/{number}", "page_start": number, "page_end": number,
        "chunk_id": 100 + number, "text": f"Passage text {number}", "similarity_score": 0.8,
    }
    data.update(overrides)
    return data


def retrieved(*passages):
    return {"question": "How do I stay hydrated?", "results": list(passages)}


def client_returning(answer=None, *, text=None):
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=answer, text=text)
    return client


@patch("knowledge_base.services.answering.retrieve_passages")
class AnswerQuestionTests(SimpleTestCase):
    def test_no_passages_skips_generation(self, retrieve):
        retrieve.return_value = retrieved()
        client = client_returning()
        result = answer_question("How do I stay hydrated?", client=client)
        self.assertEqual(result, {"question": "How do I stay hydrated?", "intent": "procedural", "answered": False, "answer": NOT_FOUND, "sources": []})
        client.models.generate_content.assert_not_called()

    def test_sources_are_the_cited_passages_with_metadata(self, retrieve):
        retrieve.return_value = retrieved(passage(1), passage(2), passage(3))
        client = client_returning(ModelAnswer(answerable=True, answer="Drink water [1]. Eat fruit [1, 3].", cited_passages=[3]))
        result = answer_question("How do I stay hydrated?", client=client)
        self.assertTrue(result["answered"])
        self.assertEqual(result["answer"], "Drink water [1]. Eat fruit [1][3].")
        self.assertEqual([s["number"] for s in result["sources"]], [1, 3])
        self.assertEqual(result["sources"][1], {"number": 3, **passage(3)})

    def test_invalid_citation_numbers_are_dropped(self, retrieve):
        retrieve.return_value = retrieved(passage(1), passage(2))
        client = client_returning(ModelAnswer(answerable=True, answer="Rest [2][7]. Walk [0].", cited_passages=[2, 9, -1]))
        result = answer_question("q", client=client)
        self.assertEqual(result["answer"], "Rest [2]. Walk .")
        self.assertEqual([s["number"] for s in result["sources"]], [2])

    def test_uncited_or_unanswerable_replies_are_not_shown(self, retrieve):
        retrieve.return_value = retrieved(passage(1))
        for reply in [
            ModelAnswer(answerable=False, answer="", cited_passages=[]),
            ModelAnswer(answerable=True, answer="   ", cited_passages=[1]),
            ModelAnswer(answerable=True, answer="Just guess.", cited_passages=[]),
            ModelAnswer(answerable=True, answer="Bad cite [4].", cited_passages=[5]),
        ]:
            with self.subTest(reply=reply):
                result = answer_question("q", client=client_returning(reply))
                self.assertEqual((result["answered"], result["answer"], result["sources"]), (False, NOT_FOUND, []))

    @override_settings(GEMINI_CHAT_MODEL="test-model")
    def test_request_grounds_the_model_in_numbered_passages(self, retrieve):
        retrieve.return_value = retrieved(passage(1), passage(2, page_start=2, page_end=3))
        client = client_returning(ModelAnswer(answerable=True, answer="Yes [1].", cited_passages=[1]))
        answer_question("  How   do I\r\nstay hydrated? ", client=client)
        retrieve.assert_called_once_with("  How   do I\r\nstay hydrated? ", 5)
        kwargs = client.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "test-model")
        self.assertIn("[1] Doc 1, page 1\nPassage text 1", kwargs["contents"])
        self.assertIn("[2] Doc 2, pages 2-3\nPassage text 2", kwargs["contents"])
        self.assertTrue(kwargs["contents"].endswith("Question:\nHow do I stay hydrated?"))
        self.assertIs(kwargs["config"].response_schema, ModelAnswer)
        self.assertEqual(kwargs["config"].response_mime_type, "application/json")
        self.assertIn("ONLY the numbered passages", kwargs["config"].system_instruction)

    def test_web_sources_use_article_labels_in_the_prompt(self, retrieve):
        retrieve.return_value = retrieved(passage(1, source_kind="web"))
        client = client_returning(ModelAnswer(answerable=True, answer="Yes [1].", cited_passages=[1]))
        answer_question("q", client=client)
        self.assertIn("Doc 1, web article", client.models.generate_content.call_args.kwargs["contents"])

    def test_prompt_and_temperature_follow_question_intent(self, retrieve):
        retrieve.return_value = retrieved(passage(1))
        cases = [
            ("How much water should I drink each day?", "factual", "Answer directly in the first sentence", 0.1),
            ("Why do older adults get dehydrated?", "explanation", "Explain causes and effects", 0.2),
            ("What are some tips to sleep better?", "procedural", "numbered list", 0.2),
            ("Write a short poem about staying hydrated", "creative", "creative format", 0.7),
        ]
        for question, intent, rule, temperature in cases:
            with self.subTest(question=question):
                client = client_returning(ModelAnswer(answerable=True, answer="Yes [1].", cited_passages=[1]))
                result = answer_question(question, client=client)
                config = client.models.generate_content.call_args.kwargs["config"]
                self.assertEqual(result["intent"], intent)
                self.assertIn(f"Question type: {intent}.", config.system_instruction)
                self.assertIn(rule, config.system_instruction)
                self.assertIn("ONLY the numbered passages", config.system_instruction)
                self.assertEqual(config.temperature, temperature)
        retrieve.assert_called_with("staying hydrated", 5)

    def test_falls_back_to_parsing_response_text(self, retrieve):
        retrieve.return_value = retrieved(passage(1))
        text = json.dumps({"answerable": True, "answer": "Yes [1].", "cited_passages": [1]})
        self.assertTrue(answer_question("q", client=client_returning(text=text))["answered"])

    def test_malformed_or_empty_response_raises(self, retrieve):
        retrieve.return_value = retrieved(passage(1))
        for text in ["not json", None, '{"answer": "missing fields"}']:
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "expected format"):
                answer_question("q", client=client_returning(text=text))

    @patch("knowledge_base.services.answering.time.sleep")
    def test_retries_rate_limits_then_succeeds(self, sleep, retrieve):
        retrieve.return_value = retrieved(passage(1))
        client = Mock()
        ok = SimpleNamespace(parsed=ModelAnswer(answerable=True, answer="Yes [1].", cited_passages=[1]), text=None)
        client.models.generate_content.side_effect = [errors.APIError(429, {}), ConnectionError(), ok]
        self.assertTrue(answer_question("q", client=client)["answered"])
        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    @patch("knowledge_base.services.answering.time.sleep")
    def test_gives_up_after_three_attempts_and_on_rejection(self, sleep, retrieve):
        retrieve.return_value = retrieved(passage(1))
        client = Mock()
        client.models.generate_content.side_effect = errors.APIError(503, {})
        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            answer_question("q", client=client)
        self.assertEqual(client.models.generate_content.call_count, 3)
        client.models.generate_content.reset_mock()
        client.models.generate_content.side_effect = errors.APIError(400, {})
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            answer_question("q", client=client)
        self.assertEqual(client.models.generate_content.call_count, 1)

    @patch.dict("os.environ", {"GEMINI_API_KEY": ""})
    def test_missing_api_key_raises(self, retrieve):
        retrieve.return_value = retrieved(passage(1))
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            answer_question("q")


class AskViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User(username="resident")
        usage_log = patch("knowledge_base.views.UsageLog.objects.create")
        self.log_usage = usage_log.start()
        self.addCleanup(usage_log.stop)

    def post(self, question):
        request = self.factory.post("/", {"question": question})
        request.user = self.user
        return ask(request)

    def test_open_to_visitors_without_login(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertContains(ask(request), 'name="question"')

    def test_get_shows_form_and_emergency_notice(self):
        request = self.factory.get("/")
        request.user = self.user
        response = ask(request)
        self.assertContains(response, 'name="question"')
        self.assertContains(response, "call 911")
        self.assertContains(response, "Signed in as resident")

    def test_validation_errors(self):
        self.assertContains(self.post("   "), "Please type a question.", status_code=400)
        self.assertContains(self.post("x" * 1001), "1,000 characters or fewer", status_code=400)

    @patch("knowledge_base.views.answer_question")
    def test_windows_line_breaks_do_not_count_double(self, answer):
        answer.return_value = {"question": "q", "answered": False, "answer": NOT_FOUND, "sources": []}
        question = ("x" * 99 + "\r\n") * 9 + "x" * 99  # 999 characters once each line break is one space
        self.assertEqual(self.post(question).status_code, 200)
        self.assertEqual(len(answer.call_args.args[0]), 999)

    @patch("knowledge_base.views.answer_question")
    def test_answer_and_sources_are_rendered_and_escaped(self, answer):
        answer.return_value = {"question": "q", "answered": True, "answer": "Drink water <script>x</script> [1].", "sources": [
            {"number": 1, **passage(1, page_start=2, page_end=3)},
            {"number": 3, **passage(3, source_url=None, publisher=None)},
        ]}
        response = self.post("How do I stay hydrated?")
        self.assertContains(response, "Drink water &lt;script&gt;x&lt;/script&gt; [1].")
        self.assertNotContains(response, "<script>x</script>")
        self.assertContains(response, '<a href="https://example.org/1" target="_blank" rel="noopener noreferrer">Doc 1</a>', html=False)
        self.assertContains(response, "Pages 2–3")
        self.assertContains(response, "Publisher 1")
        self.assertContains(response, "[3]")
        self.assertContains(response, "Page 3")
        self.assertNotContains(response, 'href="None"')
        self.assertContains(response, "Passage text 3")

    @patch("knowledge_base.views.answer_question")
    def test_not_found_answer_has_no_sources_section(self, answer):
        answer.return_value = {"question": "q", "answered": False, "answer": NOT_FOUND, "sources": []}
        response = self.post("How do I fix my car?")
        self.assertContains(response, NOT_FOUND.replace("'", "&#x27;"))
        self.assertNotContains(response, "<h2>Sources</h2>", html=False)

    @patch("knowledge_base.views.answer_question", side_effect=RuntimeError("secret detail"))
    def test_service_failure_shows_friendly_error(self, _):
        with self.assertLogs("knowledge_base.views", "ERROR"):
            response = self.post("How do I stay hydrated?")
        self.assertContains(response, "answers are unavailable right now", status_code=503)
        self.assertNotContains(response, "secret detail", status_code=503)
        self.assertFalse(self.log_usage.call_args.kwargs["success"])
