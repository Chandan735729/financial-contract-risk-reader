"""Structured error analysis — Dataset_and_Evaluation_Spec.md SS7, Phase 6
spec SS15.

`ErrorRecord.note` is a short, safe, human-authored summary — never raw
clause/document text (Phase 6 spec SS15: "preserve only safe metadata").
Every record here is generated from *synthetic* benchmark fixtures (see
`corpus/eval/README.md`), so referencing a `case_id` is safe even though a
real-document error report would need to redact further.

`KNOWN_FINDINGS` is a curated, explicit list of the real gaps this Phase 6
evaluation pass discovered — cross-referenced from the dataset modules that
found them (`adversarial_risk_cases.py`, `risk_test_holdout.py`,
`condition_ground_truth.py`) rather than re-discovering them dynamically,
since discovering *new* errors requires running the eval suite (see
`run_all.py`), while this module's job is to categorize and report them in
one place per Dataset_and_Evaluation_Spec.md SS7's required taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorCategory = Literal[
    "parsing_failure",
    "segmentation_failure",
    "retrieval_failure",
    "corpus_gap",
    "semantic_similarity_error",
    "lexical_error",
    "entity_extraction_error",
    "condition_extraction_error",
    "evidence_error",
    "classification_error",
    "severity_error",
    "confidence_error",
    "abstention_error",
    "grounding_failure",
]

_CATEGORIES: tuple[ErrorCategory, ...] = (
    "parsing_failure",
    "segmentation_failure",
    "retrieval_failure",
    "corpus_gap",
    "semantic_similarity_error",
    "lexical_error",
    "entity_extraction_error",
    "condition_extraction_error",
    "evidence_error",
    "classification_error",
    "severity_error",
    "confidence_error",
    "abstention_error",
    "grounding_failure",
)


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    category: ErrorCategory
    case_id: str
    source: str  # which dataset/script found this
    note: str  # short, safe summary - no raw document text


# Phase 6's actual findings, one record per documented gap (see each source
# module's own docstring for the full explanation).
KNOWN_FINDINGS: tuple[ErrorRecord, ...] = (
    ErrorRecord(
        category="severity_error",
        case_id="A",
        source="corpus/eval/datasets/adversarial_risk_cases.py",
        note="Canonical 'X shall pay Y if Z' phrasing scores MEDIUM (0.69) not HIGH (0.70) - "
        "condition_completeness reads partial because the consequence precedes the trigger.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="C",
        source="corpus/eval/datasets/adversarial_risk_cases.py",
        note="'No X unless Y' (conditional carve-out re-establishing risk) reads as flat "
        "negation -> LOW; the rule layer has no notion of a nested exception.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="neither_party_waives_gap",
        source="corpus/eval/datasets/adversarial_risk_cases.py",
        note="'neither...waives' is not recognized as a negation cue (risk_rules._NEGATION_CUES "
        "lacks 'neither') - misclassified as a positive rule hit.",
    ),
    ErrorRecord(
        category="condition_extraction_error",
        case_id="condition_provided_that_unsupported",
        source="corpus/eval/datasets/condition_ground_truth.py",
        note="'provided that' is not a recognized trigger marker.",
    ),
    ErrorRecord(
        category="condition_extraction_error",
        case_id="condition_subject_to_unsupported",
        source="corpus/eval/datasets/condition_ground_truth.py",
        note="'subject to' is not a recognized trigger marker.",
    ),
    ErrorRecord(
        category="condition_extraction_error",
        case_id="condition_notwithstanding_unsupported",
        source="corpus/eval/datasets/condition_ground_truth.py",
        note="'notwithstanding' is not a recognized trigger marker.",
    ),
    ErrorRecord(
        category="corpus_gap",
        case_id="test_insurance_exclusion_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="No rule or corpus pattern covers any insurance subcategory - the reference "
        "corpus is empty (corpus/README.md), so retrieval contributes zero signal in production.",
    ),
    ErrorRecord(
        category="corpus_gap",
        case_id="test_interest_rate_change_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="No rule covers interest_repayment/rate_change.",
    ),
    ErrorRecord(
        category="corpus_gap",
        case_id="test_deductible_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="No rule covers insurance/deductible.",
    ),
    ErrorRecord(
        category="corpus_gap",
        case_id="test_standalone_jury_waiver_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="No rule covers a standalone (non-arbitration) rights waiver.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="test_prepayment_fee_wording_variant",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="'early payoff fee' / 'settle...ahead of schedule' phrasing doesn't match the "
        "prepayment_penalty rule's literal primary pattern.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="test_arbitration_no_condition_marker",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="Rule fires but no if/when/unless marker present -> condition_completeness=none "
        "-> score lands just under MEDIUM_THRESHOLD.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="test_termination_without_penalty_wording_variant",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="early_termination_fee rule requires the literal phrase 'early termination'; "
        "generic 'terminate...without penalty' phrasing doesn't match.",
    ),
    ErrorRecord(
        category="classification_error",
        case_id="test_auto_renewal_annually_wording_variant",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="auto_renewal_notice rule's primary pattern requires 'automatically'/'auto-'; "
        "'renews annually' isn't matched.",
    ),
    ErrorRecord(
        category="confidence_error",
        case_id="calibration_dev_to_test_transfer",
        source="corpus/eval/run_calibration_eval.py",
        note="Isotonic calibration fit on the 15-case DEV split increases ECE on TEST "
        "(overfits a too-small sample) - do not trust the DEV-fitted mapping without a "
        "larger dataset.",
    ),
)


def summarize_by_category(records: tuple[ErrorRecord, ...] = KNOWN_FINDINGS) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(_CATEGORIES, 0)
    for record in records:
        counts[record.category] += 1
    return counts


def format_report(records: tuple[ErrorRecord, ...] = KNOWN_FINDINGS) -> str:
    lines = ["Error analysis - distribution by category (Dataset_and_Evaluation_Spec.md SS7)", "=" * 78]
    counts = summarize_by_category(records)
    for category in _CATEGORIES:
        count = counts[category]
        if count:
            lines.append(f"  {category:28s} {count}")
    lines.append("")
    lines.append(f"Total documented findings: {len(records)}")
    lines.append("")
    for record in records:
        lines.append(f"[{record.category}] {record.case_id} ({record.source})")
        lines.append(f"    {record.note}")
    return "\n".join(lines)
