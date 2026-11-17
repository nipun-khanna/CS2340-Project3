from django.conf import settings
from pgvector.django import CosineDistance

from knowledge_base.models import Document, DocumentChunk

from .embeddings import embed_text


NO_RESULTS = "No sufficiently relevant information was found in the available documents."


def retrieve_passages(question: str, top_k: int = 5) -> dict:
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        raise ValueError("question must be a nonempty string of at most 1000 characters")
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k must be an integer from 1 to 5")
    original_question = question
    question = " ".join(question.split())
    result = {"question": original_question, "results": []}
    if not DocumentChunk.objects.filter(document__status=Document.Status.COMPLETED).exists():
        result["message"] = NO_RESULTS
        return result
    vector = embed_text(question, "RETRIEVAL_QUERY")
    candidates = (
        DocumentChunk.objects.filter(document__status=Document.Status.COMPLETED)
        .select_related("document")
        .annotate(distance=CosineDistance("embedding", vector))
        .filter(distance__lte=1 - settings.RAG_MIN_SIMILARITY)
        .order_by("distance", "id")[:top_k]
    )
    for chunk in candidates:
        document = chunk.document
        result["results"].append({
            "document_id": document.pk, "title": document.title,
            "source_kind": "web" if document.relative_path.startswith("web/") else "pdf",
            "publisher": document.publisher or None, "source_url": document.source_url or None,
            "page_start": chunk.page_start, "page_end": chunk.page_end,
            "chunk_id": chunk.pk, "text": chunk.text,
            "similarity_score": round(1 - chunk.distance, 4),
        })
    if not result["results"]:
        result["message"] = NO_RESULTS
    return result
