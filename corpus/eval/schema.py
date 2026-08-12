"""Canonical evaluation ground-truth schema — Phase 6 spec SS2.

One `ClauseGroundTruth` record backs risk-classification, evidence, entity,
condition, and abstention evaluation from a single shared annotation, the
same way `Risk_Taxonomy_and_Labeling_Spec.md` SS6's `ClauseAnalysis` is the
one canonical shape the whole pipeline scores against. This mirrors
`Dataset_and_Evaluation_Spec.md` SS2's annotation schema (category,
subcategory, severity, confidence axis, evidence span, explicit negative/
ambiguous labeling) rather than inventing a parallel one.

Every dataset module under `corpus/eval/datasets/` builds a `tuple[
ClauseGroundTruth, ...]` and assigns each case to exactly one
`DatasetSplit` — see that package's `__init__.py` for what each split means
and the non-negotiable rule: `TEST` is never used to select a weight,
threshold, or calibration mapping.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import DocumentType, RiskCategory, RiskLevel  # noqa: E402


class DatasetSplit(str, Enum):
    DEV = "dev"
    TEST = "test"
    ADVERSARIAL = "adversarial"


LabelKind = Literal["positive", "negative", "ambiguous"]


@dataclass(frozen=True, slots=True)
class GroundTruthEntity:
    """Gold financial entity. `normalized_value` is the value a correct
    extractor should report in `FinancialEntity.value` (e.g. `"5"` for both
    `"5%"` and `"5.0%"`) — `None` when the case is intentionally testing an
    *unsupported* pattern (Phase 6 spec SS5's difficult cases), where the
    correct system behavior is to extract nothing (P4.7: word-form numbers,
    other currencies are documented-unsupported, not silently mis-parsed).
    """

    entity_type: Literal["percentage", "rate", "amount", "fee", "time_period"]
    raw_text: str
    normalized_value: str | None
    # `False` marks a case where NO entity of this description should be
    # extracted at all (an unsupported-pattern probe) — `raw_text` is then
    # the phrase a correct system must NOT turn into a fabricated entity.
    expected_to_be_extracted: bool = True


@dataclass(frozen=True, slots=True)
class GroundTruthEvidenceSpan:
    text: str
    supports: str  # free-text label, e.g. "prepayment_penalty trigger" — never logged/persisted


@dataclass(frozen=True, slots=True)
class ClauseGroundTruth:
    """One fully-annotated synthetic clause. Fields left `None`/empty are
    genuinely absent in the gold annotation (Phase 6 spec SS2: "Do not
    force ambiguous clauses into a confident label")."""

    case_id: str
    text: str
    split: DatasetSplit
    label_kind: LabelKind
    document_type: DocumentType = DocumentType.LOAN

    risk_category: RiskCategory | None = None
    risk_subcategory: str | None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN

    # Whether a correctly-working system SHOULD abstain on this clause.
    # Distinct from `risk_level == UNKNOWN` on the *predicted* side — this
    # is the gold expectation the abstention-quality metrics compare against
    # (Phase 6 spec SS10).
    expected_abstention: bool = False
    ambiguous: bool = False  # genuinely ambiguous per Phase 6 spec SS2/SS10

    trigger: str | None = None
    condition: str | None = None
    consequence: str | None = None
    affected_party: str | None = None

    entities: tuple[GroundTruthEntity, ...] = field(default_factory=tuple)
    evidence_spans: tuple[GroundTruthEvidenceSpan, ...] = field(default_factory=tuple)

    low_confidence_flag: bool = False  # simulates a low-segmentation-confidence clause
    notes: str = ""  # short annotator rationale — never raw third-party document content

    # `True` marks a case where the *current* pipeline is already known not
    # to reach `risk_level` (a documented scope/coverage gap — narrow rule
    # patterns, empty corpus, unsupported connective, ...), recorded here as
    # a real error-analysis finding rather than silently adjusting the gold
    # label to match whatever the engine currently outputs. See `notes` for
    # the specific reason. Reported separately from genuine regressions by
    # `run_all.py`'s acceptance-threshold check.
    known_gap: bool = False

    def __post_init__(self) -> None:
        if self.expected_abstention and self.risk_level != RiskLevel.UNKNOWN:
            raise ValueError(
                f"{self.case_id}: expected_abstention=True requires risk_level=UNKNOWN "
                "(mirrors ClauseAnalysis's own abstained<->UNKNOWN invariant)"
            )
