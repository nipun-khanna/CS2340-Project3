import json
import logging
import time

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from .services.answering import answer_question
from .services.evaluation import evaluate_case, load_cases
from .models import UsageLog
from .services.retrieval import retrieve_passages


logger = logging.getLogger(__name__)
MAX_QUESTION_LENGTH = 1000


@require_http_methods(["GET", "POST"])
def ask(request):
    context = {"question": "", "result": None, "error": None, "max_length": MAX_QUESTION_LENGTH}
    status = 200
    if request.method == "POST":
        # Browsers submit textarea line breaks as \r\n, which would otherwise count double toward the limit.
        question = " ".join(request.POST.get("question", "").split())
        context["question"] = question
        if not question:
            context["error"] = "Please type a question."
            status = 400
        elif len(question) > MAX_QUESTION_LENGTH:
            context["error"] = f"Please keep your question to {MAX_QUESTION_LENGTH:,} characters or fewer."
            status = 400
        else:
            start = time.time()
            success = True
            try:
                context["result"] = answer_question(question)
            except Exception:
                logger.exception("Answering a question failed")
                context["error"] = "Sorry, answers are unavailable right now. Please try again in a few minutes."
                status = 503
                success = False
            UsageLog.objects.create(question_length=len(question), success=success, response_seconds=time.time() - start)
    return render(request, "knowledge_base/ask.html", context, status=status)


@require_POST
def retrieve(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"error": "Developer login required"}, status=403)
    if request.content_type != "application/json":
        return JsonResponse({"error": "Content-Type must be application/json"}, status=415)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or set(payload) - {"question", "top_k"}:
            raise ValueError("Expected a JSON object with question and optional top_k")
        response = retrieve_passages(payload.get("question"), payload.get("top_k", 5))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Retrieval is temporarily unavailable"}, status=503)
    return JsonResponse(response)


@login_required
@require_http_methods(["GET", "POST"])
def developer_tools(request):
    # Staff membership is managed by the existing Django administrator.
    if not request.user.is_staff:
        return JsonResponse({"error": "Developer login required"}, status=403)
    cases = load_cases()
    context = {"cases": cases}
    status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "evaluate":
                case = next((case for case in cases if case["id"] == request.POST.get("case_id")), None)
                if case is None:
                    raise ValueError("Choose one of the known questions.")
                context["evaluation"] = evaluate_case(case)
            else:
                raise ValueError("Choose a supported action.")
        except ValueError as exc:
            context["error"] = str(exc)
            status = 400
        except Exception:
            logger.exception("Developer tool failed")
            context["error"] = "The operation failed. Check the database, API configuration, and source availability."
            status = 503
    return render(request, "knowledge_base/developer_tools.html", context, status=status)
