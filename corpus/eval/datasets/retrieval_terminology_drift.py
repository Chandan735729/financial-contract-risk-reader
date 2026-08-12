"""Terminology-drift retrieval queries — Phase 6 spec SS4 ("terminology
drift").

Supplementary to `backend/tests/fixtures/retrieval_benchmark.py` (Phase 4's
own benchmark, left untouched) — these queries reuse that file's
`CORPUS_PATTERNS` as the gold corpus but use much heavier vocabulary
substitution than that file's "paraphrase" queries (synonyms, restructured
sentences, no shared multi-word phrases with the gold pattern), specifically
to stress-test whether dense retrieval generalizes past surface wording
or lexical retrieval degrades to noise once there's no token overlap.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@dataclass(frozen=True, slots=True)
class TerminologyDriftQuery:
    text: str
    gold_index: int  # index into tests.fixtures.retrieval_benchmark.CORPUS_PATTERNS


TERMINOLOGY_DRIFT_QUERIES: tuple[TerminologyDriftQuery, ...] = (
    TerminologyDriftQuery(
        text=(
            "Settling the borrowed sum ahead of the agreed timeline triggers a "
            "two percent surcharge on whatever principal remains outstanding."
        ),
        gold_index=0,  # prepayment_penalty
    ),
    TerminologyDriftQuery(
        text=(
            "Should the borrower fall into arrears, the lending institution "
            "retains the right to seize and liquidate the pledged property."
        ),
        gold_index=3,  # foreclosure
    ),
    TerminologyDriftQuery(
        text=(
            "Coverage will not extend to any claim tied to a health condition "
            "that already existed before the policy began."
        ),
        gold_index=5,  # insurance exclusion
    ),
    TerminologyDriftQuery(
        text="By signing, the Borrower gives up any entitlement to have this matter heard by a jury.",
        gold_index=8,  # waiver
    ),
)
