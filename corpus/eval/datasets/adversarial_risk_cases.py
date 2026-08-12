"""Adversarial risk-classification cases - Phase 6 spec SS9 (cases A-I,
reproduced verbatim from the phase brief).

These are stress tests for negation, cross-reference, conditional carve-outs,
and retrieval-vs-rule conflict - not ordinary classification examples. Several
of the spec's own case descriptions are deliberately *not* a single fixed
label ("NOT globally LOW," "possibly UNKNOWN," "test carefully") - that
hedging is preserved here as `expected_levels` (must be one of) vs.
`forbidden_levels` (must not be one of) rather than forcing every case into
one gold answer that isn't actually justified by the spec text.

**This file is where Phase 6 found real gaps, and does not hide them.**
Two are recorded here rather than silently patched (Phase 6 is an
evaluation phase, not a feature/engine-change phase):

- Case A's canonical phrasing ("Borrower shall pay a 5% prepayment penalty
  if the loan is repaid early") currently scores MEDIUM (0.69), one
  weight-unit under the HIGH threshold (0.70) - not HIGH, contrary to the
  spec's explicit expectation. Root cause: `condition_extraction_service`
  only looks for a consequence *after* the trigger marker's sentence
  position; this natural "X shall Y if Z" ordering places the consequence
  (the penalty) *before* the trigger, so `condition_completeness` reads
  "partial" instead of "full" and the score falls short. See
  `run_risk_engine_eval.py`'s adversarial section output and
  docs/PROVISIONAL_DECISIONS.md "Phase 6: adversarial findings."
- `neither_party_waives_gap` (an explicit extra case, not part of the
  spec's A-I list) shows `risk_rules._NEGATION_CUES` does not include
  "neither" - "neither party waives" is misclassified as a *positive*
  arbitration_waiver rule hit instead of negative. It happens not to reach
  MEDIUM/HIGH here only because the condition chain is otherwise weak, which
  is a coincidence, not a fix.

Both are `known_gap=True` and intentionally left failing/borderline so the
regression gate has a real, honest baseline to compare future engine changes
against.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.models.enums import DocumentType, RiskLevel  # noqa: E402
from app.services.risk_engine import PatternSignal  # noqa: E402


@dataclass(frozen=True, slots=True)
class AdversarialCase:
    case_id: str
    text: str
    spec_expectation: str  # the phase-brief's own words for this case
    expected_levels: tuple[RiskLevel, ...] | None = None  # predicted level must be one of these to pass
    forbidden_levels: tuple[RiskLevel, ...] = ()  # predicted level must never be one of these
    strict: bool = (
        True  # False = spec hedges ("possibly", "likely") - failing is a soft finding, not a gate failure
    )
    known_gap: bool = False  # True = a real, already-documented limitation; reported, not gated on
    document_type: DocumentType = DocumentType.LOAN
    matched_patterns: tuple[PatternSignal, ...] = field(default_factory=tuple)
    low_confidence_flag: bool = False


ADVERSARIAL_CASES: tuple[AdversarialCase, ...] = (
    AdversarialCase(
        case_id="A",
        text="Borrower shall pay a 5% prepayment penalty if the loan is repaid early.",
        spec_expectation="HIGH",
        expected_levels=(RiskLevel.HIGH,),
        known_gap=True,  # see module docstring - currently scores MEDIUM (0.69)
    ),
    AdversarialCase(
        case_id="B",
        text="Borrower may prepay at any time without penalty.",
        spec_expectation="LOW (positive evidence of no penalty)",
        expected_levels=(RiskLevel.LOW,),
    ),
    AdversarialCase(
        case_id="C",
        text="No prepayment penalty applies unless the loan is repaid within 12 months.",
        spec_expectation="NOT globally LOW - must capture the conditional risk",
        forbidden_levels=(RiskLevel.LOW,),
        known_gap=True,  # currently scores LOW - the rule layer has no notion of a
        # conditional carve-out re-establishing risk inside a "no X unless Y" structure;
        # it only ever detects "no X" as a flat negation. Documented, not silently fixed.
    ),
    AdversarialCase(
        case_id="D",
        text="Prepayment terms are described in Section 7.",
        spec_expectation="possibly UNKNOWN - actual risk evidence is elsewhere",
        expected_levels=(RiskLevel.UNKNOWN,),
        strict=False,
    ),
    AdversarialCase(
        case_id="E",
        text="Except as provided in Section 7, no prepayment fee applies.",
        spec_expectation="test cross-reference/negation handling carefully - no fixed expected label",
        strict=False,
        # Deliberately no expected_levels/forbidden_levels: this case is
        # reported observationally (see run_risk_engine_eval.py output),
        # not scored pass/fail - the spec itself does not assert one answer.
    ),
    AdversarialCase(
        case_id="F",
        text="An administrative fee may apply.",
        spec_expectation="likely UNKNOWN/MEDIUM depending on evidence - not an automatic HIGH",
        forbidden_levels=(RiskLevel.HIGH,),
        strict=False,
    ),
    AdversarialCase(
        case_id="G",
        text="This agreement does not require arbitration and no right is waived.",
        spec_expectation="contains 'arbitration' but does NOT waive a right - must not auto-produce the highest arbitration risk",
        forbidden_levels=(RiskLevel.HIGH,),
    ),
    AdversarialCase(
        case_id="H",
        text=(
            "Borrower may prepay the loan in full at any time without incurring any "
            "penalty or additional charge."
        ),
        spec_expectation="high embedding similarity but explicit negative language - retrieval alone must not cause HIGH",
        forbidden_levels=(RiskLevel.HIGH,),
        matched_patterns=(
            PatternSignal(
                similarity_score=0.92,
                lexical_score=0.30,
                risk_category=None,
                risk_subcategory="prepayment_penalty",
                is_negative_example=False,
                taxonomy_version="taxonomy_v1",
                corpus_version="corpus_v1",
            ),
        ),
    ),
    AdversarialCase(
        case_id="I",
        text=(
            "If this loan is settled in full before the end of its term, a 5% "
            "prepayment penalty of the principal shall apply."
        ),
        spec_expectation="low embedding similarity but explicit rule + entity - engine can still reach meaningful risk",
        expected_levels=(RiskLevel.HIGH, RiskLevel.MEDIUM),
        matched_patterns=(
            PatternSignal(
                similarity_score=0.15,
                lexical_score=0.05,
                risk_category=None,
                risk_subcategory="prepayment_penalty",
                is_negative_example=False,
                taxonomy_version="taxonomy_v1",
                corpus_version="corpus_v1",
            ),
        ),
    ),
    # -- Supplementary: not part of the spec's A-I list, added by Phase 6
    # testing because it surfaced a real negation-cue gap (see module docstring).
    AdversarialCase(
        case_id="neither_party_waives_gap",
        text="Any dispute may optionally proceed to arbitration, but neither party waives any other legal right.",
        spec_expectation="(supplementary) 'neither...waives' should read as negated, like 'does not...waive'",
        forbidden_levels=(RiskLevel.HIGH, RiskLevel.MEDIUM),
        strict=False,
        known_gap=True,
    ),
)
