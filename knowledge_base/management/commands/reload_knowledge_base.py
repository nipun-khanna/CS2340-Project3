from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from knowledge_base.models import Document
from knowledge_base.services.ingestion import discover_pdfs


class Command(BaseCommand):
    help = ("Make the knowledge base match data/: remove documents whose PDF is gone, "
            "then re-extract and re-embed every PDF (web sources are retained)")

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm removing documents whose PDF is gone")

    def handle(self, *args, **options):
        data_dir = Path(settings.DATA_DIR).resolve()
        # Resolve exactly as ingest_file does, so a symlinked PDF matches the path its record was stored under.
        resolved = (path.resolve() for path in discover_pdfs())
        present = {path.relative_to(data_dir).as_posix() for path in resolved if path.is_relative_to(data_dir)}
        stale = list(Document.objects.exclude(relative_path__startswith="web/").exclude(relative_path__in=present).order_by("id"))
        if stale:
            self.stdout.write("These documents no longer have a PDF in data/ and will be removed:")
            for document in stale:
                self.stdout.write(f"  {document.pk}\t{document.title}\t{document.relative_path}")
            if not options["yes"] and input("Type yes to remove them and reload: ") != "yes":
                self.stdout.write("Cancelled")
                return
            Document.objects.filter(pk__in=[document.pk for document in stale]).delete()
            self.stdout.write(f"Removed {len(stale)} document(s) without a PDF.")
        # Each document keeps its previous version searchable until its new version is fully embedded.
        call_command("ingest_documents", force=True, stdout=self.stdout, stderr=self.stderr)
