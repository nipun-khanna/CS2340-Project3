"""Repeatable answer smoke checks, with reference answers for human review."""
import json
import logging
import re
from pathlib import Path
from time import perf_counter

from django.conf import settings

from .answering import NOT_FOUND, answer_question


logger = logging.getLogger(__name__)


def load_cases(path=None):
    cases = json.loads(Path(path or settings.BASE_DIR / "evaluation_answers.json").read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must be a nonempty JSON list.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not all(key in case for key in (
            "id", "question", "expected_answer", "expected_title", "required_concepts"
        )):
            raise ValueError("Each case needs id, question, expected_answer, expected_title, and required_concepts.")
        for key in ("id", "question", "expected_answer"):
            if not isinstance(case[key], str) or not case[key].strip():
                raise ValueError(f"Case {key} must be nonempty text.")
        if case["id"] in ids or len(case["question"]) > 1000:
            raise ValueError("Case IDs must be unique and questions at most 1,000 characters.")
        ids.add(case["id"])
        title, concepts = case["expected_title"], case["required_concepts"]
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise ValueError("expected_title must be nonempty text or null for abstention.")
        if not isinstance(concepts, list) or (title is not None and not concepts):
            raise ValueError("Answerable cases need required_concepts.")
        if any(not isinstance(group, list) or not group or any(
            not isinstance(term, str) or not term.strip() for term in group
        ) for group in concepts):
            raise ValueError("Each concept must be a nonempty list of alternative phrases.")
    return cases


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def evaluate_case(case):
    started = perf_counter()
    report = {"id": case["id"], "question": case["question"],
              "expected_answer": case["expected_answer"], "expected_title": case["expected_title"],
              "reference_file": case.get("reference_file"), "reference_pages": case.get("reference_pages", [])}
    try:
        result = answer_question(case["question"])
        answer = normalize(result["answer"])
        missing = [group for group in case["required_concepts"] if not any(
            f" {normalize(term)} " in f" {answer} " for term in group
        )]
        if case["expected_title"] is None:
            checks = {"abstained": not result["answered"] and result["answer"] == NOT_FOUND,
                      "no_sources": not result["sources"]}
        else:
            checks = {"answered": result["answered"], "expected_facts": not missing,
                      "expected_source": any(normalize(source["title"]) == normalize(case["expected_title"])
                                             for source in result["sources"]),
                      "inline_citation": any(f"[{source['number']}]" in result["answer"] for source in result["sources"])}
        report.update(status="PASS" if all(checks.values()) else "REVIEW", checks=checks,
                      missing_concepts=missing, answer=result["answer"], sources=result["sources"])
    except Exception:
        logger.exception("Known-question evaluation failed: %s", case["id"])
        # Continue the suite without exposing provider credentials or database connection strings.
        report.update(status="ERROR", error="Answer generation failed; check server configuration and logs.")
    report["elapsed_seconds"] = round(perf_counter() - started, 3)
    return report
