from django.core.management.base import BaseCommand, CommandError

from knowledge_base.models import Document


class Command(BaseCommand):
    help = "Remove a document and its chunks"

    def add_arguments(self, parser):
        parser.add_argument("document_id", type=int)
        parser.add_argument("--yes", action="store_true", help="Confirm removal without prompting")

    def handle(self, *args, **options):
        try:
            document = Document.objects.get(pk=options["document_id"])
        except Document.DoesNotExist as exc:
            raise CommandError("Document not found") from exc
        if not options["yes"]:
            answer = input(f"Remove {document.title} and its {document.chunk_count} chunks? Type yes: ")
            if answer != "yes":
                self.stdout.write("Cancelled")
                return
        title = document.title
        document.delete()
        self.stdout.write(f"Removed {title}")
