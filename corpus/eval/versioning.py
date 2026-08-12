"""Evaluation run versioning — Phase 6 spec SS17.

Every evaluation run stamps the exact versions its numbers are meaningful
against: git commit, taxonomy version, corpus version, risk-engine version,
embedding model, and this benchmark's own version. Without this, a metric
number is unattributable the moment any of those move.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

# Bump whenever a dataset module under corpus/eval/datasets/ changes in a
# way that could shift measured metrics (new/removed/edited cases) — not on
# every trivial docstring edit. Recorded on every run so a metric change can
# be attributed to "the benchmark changed" vs. "the pipeline changed."
BENCHMARK_VERSION = "eval_benchmark_v1"

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        commit = result.stdout.strip()
        return commit if result.returncode == 0 and commit else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass(frozen=True, slots=True)
class EvalRunMetadata:
    run_timestamp: str
    git_commit: str
    git_dirty: bool
    taxonomy_version: str
    corpus_version: str
    engine_version: str
    embedding_model: str
    benchmark_version: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_run_metadata(
    *,
    taxonomy_version: str,
    corpus_version: str,
    engine_version: str,
    embedding_model: str,
    benchmark_version: str = BENCHMARK_VERSION,
) -> EvalRunMetadata:
    return EvalRunMetadata(
        run_timestamp=datetime.now(UTC).isoformat(),
        git_commit=_git_commit(),
        git_dirty=_git_dirty(),
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
        engine_version=engine_version,
        embedding_model=embedding_model,
        benchmark_version=benchmark_version,
    )


def results_dir() -> Path:
    d = Path(__file__).resolve().parent / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def timestamped_output_path(run_name: str, metadata: EvalRunMetadata, *, ext: str = "json") -> Path:
    """Never overwrites a previous run's output (Phase 6 spec SS17) — the
    commit-short-sha + timestamp in the filename makes every run's output a
    new, permanent file."""
    safe_commit = metadata.git_commit[:12] if metadata.git_commit != "unknown" else "nogit"
    stamp = metadata.run_timestamp.replace(":", "").replace("-", "").replace(".", "")
    return results_dir() / f"{run_name}_{safe_commit}_{stamp}.{ext}"
