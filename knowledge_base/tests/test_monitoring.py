from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase

from knowledge_base.services.monitoring import percentile, summarize
from knowledge_base.views import monitoring


class SummarizeTests(SimpleTestCase):
    def test_no_logs(self):
        self.assertEqual(summarize([], 10, 0.05), {"requests": 0, "status": "NO DATA"})

    def test_healthy_traffic_meets_targets(self):
        logs = [(float(seconds), True) for seconds in range(1, 21)]
        summary = summarize(logs, 20, 0.05)
        self.assertEqual(summary["status"], "OK")
        self.assertEqual((summary["requests"], summary["failures"], summary["slow_requests"]), (20, 0, 0))
        self.assertEqual((summary["p50_seconds"], summary["p95_seconds"], summary["max_seconds"]), (10.0, 19.0, 20.0))
        self.assertAlmostEqual(summary["average_seconds"], 10.5)
        self.assertEqual(summary["problems"], [])

    def test_slow_and_failing_traffic_needs_attention(self):
        logs = [(2.0, True)] * 8 + [(15.0, False), (30.0, True)]
        summary = summarize(logs, 10, 0.05)
        self.assertEqual(summary["status"], "ATTENTION")
        self.assertEqual((summary["failures"], summary["failure_rate"], summary["slow_requests"]), (1, 0.1, 2))
        self.assertEqual(len(summary["problems"]), 2)
        self.assertIn("exceeds the 10s target", summary["problems"][0])
        self.assertIn("failure rate 10.0%", summary["problems"][1])

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([5.0], 0.95), 5.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.0)


class MonitoringViewTests(SimpleTestCase):
    def get(self, user, query=""):
        request = RequestFactory().get(f"/developer/monitoring/{query}")
        request.user = user
        return monitoring(request)

    def test_staff_only(self):
        self.assertEqual(self.get(User(username="resident")).status_code, 403)

    @patch("knowledge_base.views.performance_report")
    def test_renders_report_and_validates_window(self, report):
        report.return_value = {
            "hours": 24, "window": "Last 24 hours", "target_seconds": 10.0, "max_failure_rate": 0.05,
            "summary": summarize([(2.0, True), (12.0, False)], 10, 0.05), "recent_failures": [],
            "recent_logs": [SimpleNamespace(created_at="2026-11-17 03:35", question_length=32, success=False, response_seconds=0.15)],
        }
        staff = User(username="admin", is_staff=True)
        response = self.get(staff, "?hours=999")
        report.assert_called_once_with(24)
        self.assertContains(response, "Last 24 hours: ATTENTION")
        self.assertContains(response, "95th percentile (p95)")
        self.assertContains(response, "12.00 s")
        self.assertContains(response, "1 (50%)")
        self.assertContains(response, "<td>32 characters</td><td>Failed</td><td>0.15 s</td>", html=False)
        self.get(staff, "?hours=1")
        report.assert_called_with(1)
