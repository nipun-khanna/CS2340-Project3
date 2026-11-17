import math
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import UsageLog

WINDOWS_HOURS = {1: "Last hour", 24: "Last 24 hours", 168: "Last 7 days"}


def percentile(sorted_values: list[float], fraction: float) -> float:
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def summarize(logs: list[tuple[float, bool]], target_seconds: float, max_failure_rate: float) -> dict:
    if not logs:
        return {"requests": 0, "status": "NO DATA"}
    latencies = sorted(seconds for seconds, _ in logs)
    failures = sum(1 for _, success in logs if not success)
    failure_rate = failures / len(logs)
    p95 = percentile(latencies, 0.95)
    problems = []
    if p95 > target_seconds:
        problems.append(f"95th percentile response time {p95:.2f}s exceeds the {target_seconds:g}s target")
    if failure_rate > max_failure_rate:
        problems.append(f"failure rate {failure_rate:.1%} exceeds the {max_failure_rate:.1%} limit")
    return {
        "requests": len(logs),
        "failures": failures,
        "failure_rate": failure_rate,
        "average_seconds": sum(latencies) / len(latencies),
        "p50_seconds": percentile(latencies, 0.50),
        "p95_seconds": p95,
        "max_seconds": latencies[-1],
        "slow_requests": sum(1 for seconds in latencies if seconds > target_seconds),
        "status": "ATTENTION" if problems else "OK",
        "problems": problems,
    }


def performance_report(hours: int) -> dict:
    since = timezone.now() - timedelta(hours=hours)
    recent = UsageLog.objects.filter(created_at__gte=since)
    target = settings.RESPONSE_TIME_TARGET_SECONDS
    max_failure_rate = settings.MAX_FAILURE_RATE
    return {
        "hours": hours,
        "window": WINDOWS_HOURS[hours],
        "target_seconds": target,
        "max_failure_rate": max_failure_rate,
        "summary": summarize(list(recent.values_list("response_seconds", "success")), target, max_failure_rate),
        "recent_failures": list(recent.filter(success=False)[:10]),
        "recent_logs": list(recent[:25]),
    }
