from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from knowledge_base.models import DocumentChunk
from knowledge_base.services.ingestion import discover_pdfs, ingest_file


class Command(BaseCommand):
    help = "Ingest all PDFs in data/, or one PDF with --file"

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Path to a PDF inside data/")
        parser.add_argument("--force", action="store_true", help="Re-extract and re-embed even unchanged documents")

    def handle(self, *args, **options):
        if options["file"]:
            path = Path(options["file"])
            if not path.is_absolute():
                path = Path.cwd() / path
            paths = [path]
        else:
            paths = discover_pdfs()
        self.stdout.write(f"Found {len(paths)} PDF files.")
        counts = {"processed": 0, "skipped": 0, "failed": 0}
        for path in paths:
            try:
                outcome, document, sparse = ingest_file(path, force=options["force"])
                counts[outcome] += 1
                self.stdout.write(f"{outcome}: {document.title} ({path.name})")
                if sparse:
                    self.stdout.write(self.style.WARNING(f"Review sparse or image-only pages in {path.name}: {sparse}"))
            except Exception as exc:
                counts["failed"] += 1
                self.stderr.write(self.style.ERROR(f"Failed: {path.name}: {exc}"))
        self.stdout.write(f"Processed: {counts['processed']}")
        self.stdout.write(f"Skipped unchanged: {counts['skipped']}")
        self.stdout.write(f"Failed: {counts['failed']}")
        self.stdout.write(f"Total searchable chunks: {DocumentChunk.objects.filter(document__status='completed').count()}")
        if counts["failed"]:
            raise CommandError(f"{counts['failed']} document(s) failed")
