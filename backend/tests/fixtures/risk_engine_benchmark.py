"""Synthetic Risk Engine benchmark — Dataset_and_Evaluation_Spec.md SS5
("Classification (Risk Engine output)"), Phase 5 spec SS20-24.

**Synthetic and hand-authored, not the real-world benchmark
Dataset_and_Evaluation_Spec.md SS4 requires** (independently annotated real
documents, messy/scanned sources, inter-annotator agreement). Useful for (a)
proving `corpus/eval/run_risk_engine_eval.py`'s metric computations are
correct and (b) a directional regression check on the Risk Engine's
threshold/weight behavior against known structural patterns — not a
production accuracy claim. See docs/PROVISIONAL_DECISIONS.md "Phase 5: risk
engine evaluation is synthetic-only" (same posture as Phase 3/4's synthetic
benchmarks, P3.6/P4.9).

Each case's `gold_risk_level` is the level a correctly working engine should
assign, by construction (the text was written to exercise a specific,
documented Risk Engine behavior — see each case's inline comment).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import DocumentType, RiskCategory
from app.services.risk_engine import PatternSignal


@dataclass(frozen=True, slots=True)
class RiskBenchmarkCase:
    name: str
    text: str
    gold_risk_level: str  # "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN"
    document_type: DocumentType = DocumentType.LOAN
    matched_patterns: tuple[PatternSignal, ...] = field(default_factory=tuple)
    low_confidence_flag: bool = False


def _pattern(
    *,
    similarity: float,
    lexical: float,
    category: RiskCategory | None,
    subcategory: str | None,
    is_negative_example: bool = False,
) -> PatternSignal:
    return PatternSignal(
        similarity_score=similarity,
        lexical_score=lexical,
        risk_category=category,
        risk_subcategory=subcategory,
        is_negative_example=is_negative_example,
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
    )


BENCHMARK_CASES: tuple[RiskBenchmarkCase, ...] = (
    # ---- HIGH: rule + corroborating entity (Risk_Taxonomy_and_Labeling_Spec.md SS4 positive example) ----
    RiskBenchmarkCase(
        name="prepayment_penalty_with_percentage",
        text=(
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        ),
        gold_risk_level="HIGH",
    ),
    RiskBenchmarkCase(
        name="early_termination_fee_with_amount",
        text=(
            "If this agreement is terminated before the end of the term, an early "
            "termination fee of Rs. 5,000 shall apply."
        ),
        gold_risk_level="HIGH",
    ),
    RiskBenchmarkCase(
        name="missed_payment_acceleration_with_amount",
        text=(
            "If the borrower fails to pay any installment of INR 10,000, the lender may "
            "accelerate the entire outstanding balance, making it immediately due."
        ),
        gold_risk_level="HIGH",
    ),
    # ---- MEDIUM: rule hit alone, no corroborating entity ----
    RiskBenchmarkCase(
        name="acceleration_rule_without_entity",
        text="In case of late payment, acceleration of the entire outstanding balance shall apply immediately.",
        gold_risk_level="MEDIUM",
    ),
    RiskBenchmarkCase(
        name="auto_renewal_with_notice_no_entity",
        text="Unless the policyholder provides notice, this policy renews automatically for a further period.",
        gold_risk_level="MEDIUM",
    ),
    RiskBenchmarkCase(
        name="arbitration_waiver_no_entity",
        text=(
            "If a dispute arises under this agreement, it shall be resolved through "
            "binding arbitration, and the parties waive the right to a jury trial."
        ),
        gold_risk_level="MEDIUM",
        document_type=DocumentType.LOAN,
    ),
    # ---- LOW: explicit negation / confirmed absence (Risk_Taxonomy_and_Labeling_Spec.md SS4 negative example) ----
    RiskBenchmarkCase(
        name="prepayment_without_penalty",
        text="Borrower may prepay at any time without penalty.",
        gold_risk_level="LOW",
    ),
    RiskBenchmarkCase(
        name="no_additional_termination_fee",
        text="Early termination is permitted with no additional fee.",
        gold_risk_level="LOW",
    ),
    RiskBenchmarkCase(
        name="negated_with_supporting_negative_example_match",
        text="Borrower may make additional principal payments at any time without penalty.",
        gold_risk_level="LOW",
        matched_patterns=(
            _pattern(
                similarity=0.88,
                lexical=0.4,
                category=RiskCategory.FINANCIAL_COST,
                subcategory="prepayment_penalty",
                is_negative_example=True,
            ),
        ),
    ),
    # ---- UNKNOWN: ambiguous, no-signal, or gated-out ----
    RiskBenchmarkCase(
        name="ambiguous_vague_prepayment",
        text="Prepayment provisions may apply under certain circumstances.",
        gold_risk_level="UNKNOWN",
    ),
    RiskBenchmarkCase(
        name="boilerplate_governing_law",
        text="This agreement shall be governed by the laws of the State.",
        gold_risk_level="UNKNOWN",
    ),
    RiskBenchmarkCase(
        name="high_similarity_but_explicitly_negated",
        text="Borrower may prepay at any time without penalty.",
        gold_risk_level="LOW",  # negation still wins even against a strong dense match
        matched_patterns=(
            _pattern(
                similarity=0.9,
                lexical=0.5,
                category=RiskCategory.FINANCIAL_COST,
                subcategory="prepayment_penalty",
            ),
        ),
    ),
    RiskBenchmarkCase(
        name="wrong_category_for_document_type",
        text="A waiting period of 90 days applies before coverage under this policy becomes effective.",
        gold_risk_level="UNKNOWN",
        document_type=DocumentType.LOAN,
        matched_patterns=(
            _pattern(
                similarity=0.95,
                lexical=0.8,
                category=RiskCategory.INSURANCE,
                subcategory="waiting_period",
            ),
        ),
    ),
    RiskBenchmarkCase(
        name="low_segmentation_confidence_forces_unknown",
        text="Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months.",
        gold_risk_level="UNKNOWN",
        low_confidence_flag=True,
    ),
    RiskBenchmarkCase(
        name="definitions_boilerplate",
        text='"Business Day" means any day other than a Saturday, Sunday, or public holiday.',
        gold_risk_level="UNKNOWN",
    ),
)
