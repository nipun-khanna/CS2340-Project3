import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from knowledge_base.services.retrieval import retrieve_passages


class Command(BaseCommand):
    help = "Check expected source documents in retrieval top results"

    def add_arguments(self, parser):
        parser.add_argument("--top-k", type=int, default=5)

    def handle(self, *args, **options):
        cases = json.loads((Path(settings.BASE_DIR) / "evaluation_questions.json").read_text(encoding="utf-8"))
        passed = 0
        for case in cases:
            result = retrieve_passages(case["question"], options["top_k"])
            found = {item["title"] for item in result["results"]}
            expected = case["expected_title"]
            ok = (expected in found) if expected else not result["results"]
            passed += ok
            self.stdout.write(f"{'PASS' if ok else 'REVIEW'}: {case['question']} | expected={expected or 'no result'} | returned={', '.join(found) or 'none'}")
        self.stdout.write(f"Matched expectations: {passed}/{len(cases)}")
