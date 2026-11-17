import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from knowledge_base.services.evaluation import evaluate_case, load_cases


class Command(BaseCommand):
    help = "Compare generated answers with known questions, facts, citations, and abstention expectations"

    def add_arguments(self, parser):
        parser.add_argument("--cases", help="JSON case file (default: evaluation_answers.json)")
        parser.add_argument("--output", help="Save full answers, checks, sources, and timings as JSON")

    def handle(self, *args, **options):
        try:
            cases = load_cases(options["cases"])
        except (OSError, ValueError) as exc:
            raise CommandError(f"Invalid evaluation cases: {exc}") from exc
        reports = []
        self.stdout.write("Automated smoke checks; compare full answers with references for human review.")
        for case in cases:
            report = evaluate_case(case)
            reports.append(report)
            self.stdout.write(f"{report['status']}: {case['id']} ({report['elapsed_seconds']}s)")
            for name, passed in report.get("checks", {}).items():
                if not passed:
                    self.stdout.write(f"  Needs review: {name}")
            if report.get("error"):
                self.stdout.write(f"  {report['error']}")
        passed = sum(report["status"] == "PASS" for report in reports)
        summary = {"generated_at": timezone.now().isoformat(), "model": settings.GEMINI_CHAT_MODEL,
                   "min_similarity": settings.RAG_MIN_SIMILARITY,
                   "passed": passed, "total": len(reports), "results": reports}
        if options["output"]:
            try:
                Path(options["output"]).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                raise CommandError(f"Could not write evaluation report: {exc}") from exc
        self.stdout.write(f"Matched expectations: {passed}/{len(reports)}")
        if passed != len(reports):
            raise CommandError("Some answers need review. Inspect the checks and full report.")
