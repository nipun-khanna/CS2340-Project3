import json
import logging
import time
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from .models import Document, UsageLog
from .services.answering import answer_question
from .services.evaluation import evaluate_case, load_cases
from .services.ingestion import discover_pdfs, ingest_file
from .services.monitoring import WINDOWS_HOURS, performance_report
from .services.retrieval import retrieve_passages
from .services.web_ingestion import ingest_url


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
@require_http_methods(["GET"])
def monitoring(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "Developer login required"}, status=403)
    try:
        hours = int(request.GET.get("hours", 24))
    except ValueError:
        hours = 24
    if hours not in WINDOWS_HOURS:
        hours = 24
    context = {"windows": WINDOWS_HOURS.items(), "report": performance_report(hours)}
    return render(request, "knowledge_base/monitoring.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def developer_tools(request):
    # Staff membership is managed by the existing Django administrator.
    if not request.user.is_staff:
        return JsonResponse({"error": "Developer login required"}, status=403)
    data_dir = Path(settings.DATA_DIR).resolve()
    files = {path.relative_to(data_dir).as_posix(): path for path in discover_pdfs()}
    cases = load_cases()
    context = {"files": files, "cases": cases, "allowed_hosts": settings.INGEST_ALLOWED_HOSTS}
    status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "evaluate":
                case = next((case for case in cases if case["id"] == request.POST.get("case_id")), None)
                if case is None:
                    raise ValueError("Choose one of the known questions.")
                context["evaluation"] = evaluate_case(case)
            elif action in ("pdf", "web"):
                if action == "pdf":
                    path = files.get(request.POST.get("pdf"))
                    if path is None:
                        raise ValueError("Choose a PDF from the dataset.")
                    outcome, document, sparse = ingest_file(path)
                else:
                    outcome, document, sparse = ingest_url(request.POST.get("url", ""))
                context["message"] = f"{outcome.capitalize()}: {document.title} ({document.chunk_count} chunks)."
                if sparse:
                    context["message"] += f" Review sparse pages: {sparse}."
            elif action in ("clear", "reload"):
                if request.POST.get("confirm") != "yes":
                    raise ValueError(f"Tick the confirmation box to {action} the knowledge base.")
                output = StringIO()
                command = "clear_knowledge_base" if action == "clear" else "reload_knowledge_base"
                try:
                    call_command(command, yes=True, stdout=output, stderr=output)
                except CommandError as exc:
                    raise RuntimeError(output.getvalue()) from exc
                # Reload ends with a four-line summary of processed, skipped, failed, and searchable chunks.
                context["message"] = " ".join(output.getvalue().strip().splitlines()[-4 if action == "reload" else -1:])
            else:
                raise ValueError("Choose a supported action.")
        except ValueError as exc:
            context["error"] = str(exc)
            status = 400
        except Exception:
            logger.exception("Developer tool failed")
            context["error"] = "The operation failed. Check the database, API configuration, and source availability."
            status = 503
    context["documents"] = Document.objects.order_by("title")
    return render(request, "knowledge_base/developer_tools.html", context, status=status)
