from django.contrib import admin

from .models import Document, DocumentChunk, UsageLog


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "filename", "status", "chunk_count", "last_ingested_at")
    search_fields = ("title", "filename", "publisher")
    readonly_fields = ("filename", "checksum", "relative_path", "status", "error_message", "page_count", "chunk_count", "created_at", "last_ingested_at")


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "chunk_index", "page_start", "page_end")
    readonly_fields = ("document", "text", "chunk_index", "page_start", "page_end", "embedding", "created_at")


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "question_length", "success", "response_seconds")
    list_filter = ("success",)
