from django.core.management.base import BaseCommand

from knowledge_base.models import Document


class Command(BaseCommand):
    help = "List ingested documents"

    def handle(self, *args, **options):
        for doc in Document.objects.order_by("id"):
            date = doc.last_ingested_at.isoformat() if doc.last_ingested_at else "never"
            self.stdout.write(f"{doc.pk}\t{doc.title}\t{doc.filename}\t{doc.status}\t{doc.chunk_count} chunks\t{date}")
