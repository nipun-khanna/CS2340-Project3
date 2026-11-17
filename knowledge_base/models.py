from django.db import models
from pgvector.django import VectorField


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    filename = models.CharField(max_length=255)
    title = models.CharField(max_length=500)
    publisher = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    relative_path = models.CharField(max_length=500, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_message = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_ingested_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title


class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    text = models.TextField()
    chunk_index = models.PositiveIntegerField()
    page_start = models.PositiveIntegerField()
    page_end = models.PositiveIntegerField()
    embedding = VectorField(dimensions=768)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(fields=["document", "chunk_index"], name="unique_document_chunk_index"),
            models.CheckConstraint(condition=models.Q(page_start__gte=1), name="chunk_page_start_positive"),
            models.CheckConstraint(condition=models.Q(page_end__gte=models.F("page_start")), name="chunk_page_order"),
        ]


class UsageLog(models.Model):
    # Metadata only: question text is not stored, since it may contain private health details.
    created_at = models.DateTimeField(auto_now_add=True)
    question_length = models.PositiveIntegerField()
    success = models.BooleanField()
    response_seconds = models.FloatField()

    class Meta:
        ordering = ["-created_at"]
