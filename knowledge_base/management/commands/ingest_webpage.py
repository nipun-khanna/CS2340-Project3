from django.core.management.base import BaseCommand, CommandError

from knowledge_base.services.web_ingestion import ingest_url


class Command(BaseCommand):
    help = "Scrape and ingest one HTML article from a trusted public health website"

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        try:
            outcome, document, _ = ingest_url(options["url"], force=options["force"])
        except Exception as exc:
            raise CommandError(f"Webpage ingestion failed: {exc}") from exc
        self.stdout.write(f"{outcome}: {document.title} ({document.chunk_count} chunks)")
