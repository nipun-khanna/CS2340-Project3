import os
import re
import time

from django.conf import settings
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from .prompts import search_query, select_prompt
from .retrieval import retrieve_passages


NOT_FOUND = ("I couldn't find an answer to that in the available health documents. "
             "Please ask a doctor, nurse, or pharmacist.")

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


class ModelAnswer(BaseModel):
    answerable: bool
    answer: str
    cited_passages: list[int]


def answer_question(question: str, *, client=None) -> dict:
    normalized = " ".join(question.split())
    strategy, system_instruction = select_prompt(normalized)
    retrieved = retrieve_passages(search_query(question, strategy.intent), 5)
    result = {"question": normalized, "intent": strategy.intent, "answered": False, "answer": NOT_FOUND, "sources": []}
    passages = retrieved["results"]
    if not passages:
        return result

    reply = _generate(normalized, passages, client, system_instruction, strategy.temperature)
    if not reply.answerable or not reply.answer.strip():
        return result

    valid = range(1, len(passages) + 1)
    inline = {int(n) for group in _MARKER.findall(reply.answer) for n in group.split(",")}
    cited = sorted({n for n in set(reply.cited_passages) | inline if n in valid})
    if not cited:
        # An uncited health answer cannot be checked by the reader, so it is not shown.
        return result

    def keep_valid_markers(match):
        numbers = [int(n) for n in match.group(1).split(",")]
        return "".join(f"[{n}]" for n in numbers if n in valid)

    result["answered"] = True
    result["answer"] = _MARKER.sub(keep_valid_markers, reply.answer).strip()
    result["sources"] = [{"number": n, **passages[n - 1]} for n in cited]
    return result


def _generate(question: str, passages: list[dict], client, system_instruction: str, temperature: float) -> ModelAnswer:
    if client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        client = genai.Client(api_key=key)
    numbered = "\n\n".join(
        f"[{i}] {p['title']}, {_pages(p)}\n{p['text']}" for i, p in enumerate(passages, 1)
    )
    contents = f"Passages:\n\n{numbered}\n\nQuestion:\n{question}"
    config = types.GenerateContentConfig(
        system_instruction=system_instruction, temperature=temperature,
        response_mime_type="application/json", response_schema=ModelAnswer,
    )
    for attempt in range(3):
        try:
            response = client.models.generate_content(model=settings.GEMINI_CHAT_MODEL, contents=contents, config=config)
            break
        except errors.APIError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError("Answer request was rejected") from exc
            if attempt == 2:
                raise RuntimeError("Answer request failed after 3 attempts") from exc
            time.sleep(2 ** attempt)
        except (TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise RuntimeError("Answer request failed after 3 attempts") from exc
            time.sleep(2 ** attempt)
    if isinstance(response.parsed, ModelAnswer):
        return response.parsed
    try:
        return ModelAnswer.model_validate_json(response.text or "")
    except ValueError as exc:
        raise RuntimeError("Answer response was not in the expected format") from exc


def _pages(passage: dict) -> str:
    if passage.get("source_kind") == "web":
        return "web article"
    if passage["page_start"] == passage["page_end"]:
        return f"page {passage['page_start']}"
    return f"pages {passage['page_start']}-{passage['page_end']}"
