"""In-process operational metrics — Phase 11.

Safe aggregates only: counters and duration statistics, never raw content,
never a per-document or per-user identifier (Security_and_Privacy_v2.md
SS1/SS9 — the same non-negotiable line `app/core/logging.py`'s field
allowlist already draws for logs; metrics get the identical treatment,
aggregated rather than per-event, so there is nothing here to redact in the
first place). In-process, single-process state — same "MVP in-process, no
new distributed infrastructure" precedent `app/core/rate_limit.py` already
established. Not durable across restarts, and not shared across worker
processes/instances; a real multi-instance deployment would need a shared
metrics backend (Prometheus + a pushgateway, a hosted metrics service,
etc.) to aggregate across instances — out of scope for this MVP, the same
class of documented limitation as the in-process rate limiter.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class _DurationStats:
    count: int = 0
    total_seconds: float = 0.0
    min_seconds: float = 0.0
    max_seconds: float = 0.0

    def record(self, seconds: float) -> None:
        if self.count == 0:
            self.min_seconds = seconds
            self.max_seconds = seconds
        else:
            self.min_seconds = min(self.min_seconds, seconds)
            self.max_seconds = max(self.max_seconds, seconds)
        self.count += 1
        self.total_seconds += seconds

    def snapshot(self) -> dict[str, float | int]:
        avg = self.total_seconds / self.count if self.count else 0.0
        return {
            "count": self.count,
            "total_seconds": round(self.total_seconds, 3),
            "avg_seconds": round(avg, 3),
            "min_seconds": round(self.min_seconds, 3),
            "max_seconds": round(self.max_seconds, 3),
        }


class MetricsRegistry:
    """Thread-safe in-process counters/durations, keyed by a fixed, known
    set of event names (see the module-level constants below) — callers
    increment by name, nothing here accepts arbitrary free-text content."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._durations: dict[str, _DurationStats] = {}

    def increment(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def observe_duration_seconds(self, name: str, seconds: float) -> None:
        with self._lock:
            self._durations.setdefault(name, _DurationStats()).record(seconds)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = dict(self._counters)
            durations = {name: stats.snapshot() for name, stats in self._durations.items()}
        return {"counters": counters, "durations": durations}

    def reset(self) -> None:
        """Test-only escape hatch — mirrors `InMemoryRateLimiter.reset()` /
        `reset_upload_rate_limiter()`; never called from application code."""
        with self._lock:
            self._counters.clear()
            self._durations.clear()


# Fixed, known event names — the closed set this phase's spec asked for:
# uploads, completed/failed jobs, durations, generation/grounding failures,
# fallback rate, rate-limit events, cleanup events.
DOCUMENTS_UPLOADED = "documents_uploaded"
PIPELINE_JOBS_COMPLETED = "pipeline_jobs_completed"
PIPELINE_JOBS_FAILED = "pipeline_jobs_failed"
PIPELINE_JOB_DURATION_SECONDS = "pipeline_job_duration_seconds"
EXPLANATIONS_GENERATED = "explanations_generated"
EXPLANATIONS_GENERATION_FAILED = "explanations_generation_failed"
EXPLANATIONS_FALLBACK_USED = "explanations_fallback_used"
UPLOAD_RATE_LIMIT_REJECTIONS = "upload_rate_limit_rejections"
RETENTION_DOCUMENTS_DELETED = "retention_documents_deleted"
RETENTION_DOCUMENTS_DELETION_FAILED = "retention_documents_deletion_failed"
RETENTION_CLEANUP_RUNS = "retention_cleanup_runs"

metrics = MetricsRegistry()


def reset_metrics() -> None:
    metrics.reset()
