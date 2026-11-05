import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services.retrieval import retrieve_passages


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
