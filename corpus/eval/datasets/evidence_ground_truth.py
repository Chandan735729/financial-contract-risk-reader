"""Evidence ground truth — Phase 6 spec SS7.

Two collections:

- `EVIDENCE_CLAUSE_CASES`: end-to-end cases (real entity/condition/rule
  extraction -> Evidence Engine) with hand-verified gold evidence spans
  (verified against actual pipeline output before being recorded — see
  `run_evidence_eval.py`).
- `EVIDENCE_INTEGRITY_PROBES`: direct adversarial inputs to
  `evidence_engine.assemble_and_verify_evidence` — correct, wrong-offset,
  cross-clause, and fabricated candidates — each with a known correct
  verify/reject outcome. This is the same class of case Phase 5's
  `test_evidence_engine.py` unit-tests individually; here they are re-run as
  part of the Phase 6 evaluation harness so "fabricated evidence never
  verifies" is a *measured, reported* safety metric
  (`percentage of HIGH/MEDIUM results carrying verified evidence`), not
  only a unit-test assertion.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from corpus.eval.schema import ClauseGroundTruth, DatasetSplit, GroundTruthEvidenceSpan  # noqa: E402

EVIDENCE_CLAUSE_CASES: tuple[ClauseGroundTruth, ...] = (
    ClauseGroundTruth(
        case_id="evidence_prepayment_penalty",
        text="Borrower shall pay a prepayment penalty equal to 5% if the loan is repaid early.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        evidence_spans=(
            GroundTruthEvidenceSpan("5%", "entity"),
            GroundTruthEvidenceSpan("if the loan is repaid early", "condition/trigger"),
            GroundTruthEvidenceSpan("prepayment penalty", "rule"),
        ),
    ),
    ClauseGroundTruth(
        case_id="evidence_early_termination_fee",
        text=(
            "An early termination fee of Rs. 5,000 applies if the agreement is "
            "terminated before the end of the term."
        ),
        split=DatasetSplit.DEV,
        label_kind="positive",
        evidence_spans=(
            GroundTruthEvidenceSpan("Rs. 5,000", "entity"),
            GroundTruthEvidenceSpan("if the agreement is terminated", "condition/trigger"),
            GroundTruthEvidenceSpan("before the end of the term", "condition/qualifier"),
            GroundTruthEvidenceSpan("early termination fee", "rule"),
        ),
    ),
    ClauseGroundTruth(
        case_id="evidence_auto_renewal_notice",
        text="This agreement renews automatically unless the policyholder provides notice.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        evidence_spans=(
            GroundTruthEvidenceSpan("unless the policyholder provides notice", "condition/trigger"),
            GroundTruthEvidenceSpan("renews automatically unless the policyholder provides notice", "rule"),
        ),
    ),
    ClauseGroundTruth(
        case_id="evidence_none_expected",
        text="This section defines terms used elsewhere in this agreement.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        evidence_spans=(),
        notes="Boilerplate with no rule/entity/condition signal — correct output is zero verified spans.",
    ),
)


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityProbe:
    """Direct `EvidenceCandidate`-shaped adversarial input — see
    `evidence_engine.EvidenceCandidate`. `source` mirrors
    `evidence_engine.EvidenceSource`."""

    probe_id: str
    category: Literal["correct", "wrong_offset", "cross_clause", "fabricated", "empty", "bad_offset_range"]
    clause_text: str
    candidate_text: str
    candidate_start: int | None
    candidate_end: int | None
    should_verify: bool


EVIDENCE_INTEGRITY_PROBES: tuple[EvidenceIntegrityProbe, ...] = (
    EvidenceIntegrityProbe(
        probe_id="correct_exact_span",
        category="correct",
        clause_text="Borrower shall pay a prepayment penalty of 5%.",
        candidate_text="prepayment penalty",
        candidate_start=21,
        candidate_end=39,
        should_verify=True,
    ),
    EvidenceIntegrityProbe(
        probe_id="wrong_offset_shifted",
        category="wrong_offset",
        clause_text="Borrower shall pay a prepayment penalty of 5%.",
        candidate_text="prepayment penalty",
        candidate_start=10,
        candidate_end=29,  # points at "shall pay a prepay" instead
        should_verify=False,
    ),
    EvidenceIntegrityProbe(
        probe_id="cross_clause_text",
        category="cross_clause",
        clause_text="This clause concerns renewal terms only.",
        candidate_text="Borrower shall pay a prepayment penalty of 5%.",  # from a different clause
        candidate_start=0,
        candidate_end=47,
        should_verify=False,
    ),
    EvidenceIntegrityProbe(
        probe_id="fabricated_amount",
        category="fabricated",
        clause_text="Borrower shall pay a prepayment penalty of 5%.",
        candidate_text="a 50% penalty applies immediately",  # not present anywhere in clause_text
        candidate_start=0,
        candidate_end=34,
        should_verify=False,
    ),
    EvidenceIntegrityProbe(
        probe_id="empty_span",
        category="empty",
        clause_text="Borrower shall pay a prepayment penalty of 5%.",
        candidate_text="",
        candidate_start=0,
        candidate_end=0,
        should_verify=False,
    ),
    EvidenceIntegrityProbe(
        probe_id="offset_beyond_text_length",
        category="bad_offset_range",
        clause_text="Short clause.",
        candidate_text="Short clause.",
        candidate_start=0,
        candidate_end=500,
        should_verify=False,
    ),
)
