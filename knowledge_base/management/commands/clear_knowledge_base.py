from django.core.management.base import BaseCommand

from knowledge_base.models import Document, DocumentChunk


class Command(BaseCommand):
    help = "Remove every document and chunk from the knowledge base. PDFs in data/ are not touched."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm removal without prompting")

    def handle(self, *args, **options):
        documents = Document.objects.count()
        if not documents:
            self.stdout.write("The knowledge base is already empty.")
            return
        if not options["yes"]:
            chunks = DocumentChunk.objects.count()
            answer = input(f"Remove all {documents} documents and {chunks} chunks? PDFs in data/ are kept. Type yes: ")
            if answer != "yes":
                self.stdout.write("Cancelled")
                return
        _, deleted = Document.objects.all().delete()
        self.stdout.write(f"Removed {deleted.get('knowledge_base.Document', 0)} documents and "
                          f"{deleted.get('knowledge_base.DocumentChunk', 0)} chunks. "
                          "Run ingest_documents to rebuild the knowledge base.")
