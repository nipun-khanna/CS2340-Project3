import json

from django.core.management.base import BaseCommand, CommandError

from knowledge_base.services.retrieval import retrieve_passages


class Command(BaseCommand):
    help = "Search the knowledge base"

    def add_arguments(self, parser):
        parser.add_argument("question")
        parser.add_argument("--top-k", type=int, default=5)

    def handle(self, *args, **options):
        try:
            result = retrieve_passages(options["question"], options["top_k"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, indent=2))
