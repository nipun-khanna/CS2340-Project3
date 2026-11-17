import hashlib
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from knowledge_base.models import Document, DocumentChunk

from .chunker import chunk_pages
from .embeddings import embed_text
from .pdf_extractor import extract_pdf


def discover_pdfs() -> list[Path]:
    data_dir = Path(settings.DATA_DIR).resolve()
    return sorted(p for p in data_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def ingest_file(path: Path, *, force: bool = False) -> tuple[str, Document, list[int]]:
    data_dir = Path(settings.DATA_DIR).resolve()
    path = Path(path).resolve()
    if path.suffix.lower() != ".pdf" or not path.is_file() or not path.is_relative_to(data_dir):
        raise ValueError("File must be an existing PDF inside data/")
    relative = path.relative_to(data_dir).as_posix()
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return _ingest_document(relative, path.name, checksum, lambda: extract_pdf(path), force=force)


def _ingest_document(relative, filename, checksum, extract, *, force=False, source_url=None):
    """Prepare all chunks before replacing a searchable version, for either ingestion method."""
    previous = Document.objects.filter(relative_path=relative).first()
    if not force and previous and previous.status == Document.Status.COMPLETED and previous.checksum == checksum:
        return "skipped", previous, []
    if previous is None:
        Document.objects.create(relative_path=relative, filename=filename, title=Path(filename).stem,
                                status=Document.Status.PROCESSING)
    elif previous.status != Document.Status.COMPLETED:
        Document.objects.filter(pk=previous.pk).update(status=Document.Status.PROCESSING, error_message="")

    try:
        extracted = extract()
        chunks = chunk_pages(extracted.pages, settings.RAG_CHUNK_TOKENS, settings.RAG_CHUNK_OVERLAP)
        if not chunks:
            raise ValueError("Document has no usable text after cleaning")
        vectors = [embed_text(chunk.text, "RETRIEVAL_DOCUMENT") for chunk in chunks]
        with transaction.atomic():
            document, _ = Document.objects.select_for_update().get_or_create(
                relative_path=relative,
                defaults={"filename": filename, "title": Path(filename).stem, "status": Document.Status.PROCESSING},
            )
            document.chunks.all().delete()
            document.filename = filename
            # Preserve curated admin edits on subsequent ingestion.
            if not document.last_ingested_at:
                document.title = extracted.title or Path(filename).stem
                document.publisher = extracted.publisher
            if source_url is not None:
                document.source_url = source_url
            document.checksum = checksum
            document.page_count = extracted.page_count
            document.chunk_count = len(chunks)
            document.status = Document.Status.COMPLETED
            document.error_message = ""
            document.last_ingested_at = timezone.now()
            document.save()
            DocumentChunk.objects.bulk_create([
                DocumentChunk(document=document, text=chunk.text, chunk_index=i,
                              page_start=chunk.page_start, page_end=chunk.page_end, embedding=vector)
                for i, (chunk, vector) in enumerate(zip(chunks, vectors))
            ])
        return "processed", document, extracted.sparse_pages
    except Exception as exc:
        # A previously completed version remains searchable when preparation fails.
        if previous and previous.status == Document.Status.COMPLETED:
            Document.objects.filter(pk=previous.pk).update(error_message=str(exc)[:1000])
        else:
            Document.objects.update_or_create(
                relative_path=relative,
                defaults={"filename": filename, "title": Path(filename).stem, "status": Document.Status.FAILED,
                          "error_message": str(exc)[:1000]},
            )
        raise
