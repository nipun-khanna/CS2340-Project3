import os
import re
import time

from django.conf import settings
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from .retrieval import retrieve_passages


NOT_FOUND = ("I couldn't find an answer to that in the available health documents. "
             "Please ask a doctor, nurse, or pharmacist.")

SYSTEM_INSTRUCTION = """You answer health questions from older adults using ONLY the numbered passages you are given.
Rules:
- Use only facts stated in the passages. Never add outside medical knowledge.
- Cite the passage after each sentence that uses it, like [1] or [2][3].
- Write in plain, friendly language a non-expert can follow. Keep the answer under 200 words.
- Do not diagnose, and do not tell anyone to start, stop, or change a medicine or dose. Where it fits, suggest talking to a doctor, nurse, or pharmacist.
- If the question describes a possible emergency (such as chest pain, trouble breathing, a serious fall, or signs of a stroke), first tell the person to call 911. This is the one statement you may make without a citation.
- If the passages do not answer the question, set answerable to false and leave answer empty and cited_passages empty."""

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


class ModelAnswer(BaseModel):
    answerable: bool
    answer: str
    cited_passages: list[int]


def answer_question(question: str, *, client=None) -> dict:
    retrieved = retrieve_passages(question, 5)
    result = {"question": retrieved["question"], "answered": False, "answer": NOT_FOUND, "sources": []}
    passages = retrieved["results"]
    if not passages:
        return result

    reply = _generate(" ".join(question.split()), passages, client)
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


def _generate(question: str, passages: list[dict], client) -> ModelAnswer:
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
        system_instruction=SYSTEM_INSTRUCTION, temperature=0.2,
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
