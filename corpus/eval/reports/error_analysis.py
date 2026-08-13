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

**PHASE_6.5 update:** 9 of the original 15 findings below are fixed
(entries removed; see each dataset module's own updated docstring/notes for
the fix). 6 remain, 2 of them newly split out to accurately describe the
post-fix state (a rule now covers the category but its output diverges from
the TEST gold label on severity, rather than "no coverage at all"). See
`docs/PROVISIONAL_DECISIONS.md` P6.6/P6.8/P6.9 and the Phase 6.5 final
report for the full before/after picture — this module intentionally only
lists what is *still* wrong, not a changelog of what was fixed.
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


# Phase 6's original findings that PHASE_6.5 fixed (kept here, commented,
# as a record of what was closed and how — not re-added to KNOWN_FINDINGS,
# which lists only what's still wrong):
#
# - severity_error "A": consequence-before-trigger extraction fix (P6.6/P6.9).
# - classification_error "C": conditional-exception polarity (P6.9).
# - classification_error "neither_party_waives_gap": added "neither" cue.
# - condition_extraction_error x3 ("provided that"/"subject to"/
#   "notwithstanding" unsupported): all three added as trigger markers.
# - classification_error "test_prepayment_fee_wording_variant": broadened
#   prepayment_penalty primary pattern.
# - classification_error "test_termination_without_penalty_wording_variant":
#   broadened early_termination_fee primary pattern.
# - classification_error "test_auto_renewal_annually_wording_variant":
#   broadened auto_renewal_notice primary + secondary pattern.
#
# Still-open findings, one record per documented gap (see each source
# module's own docstring/notes for the full explanation).
KNOWN_FINDINGS: tuple[ErrorRecord, ...] = (
    ErrorRecord(
        category="severity_error",
        case_id="test_interest_rate_change_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="PHASE_6.5 PARTIAL: a new interest_rate_change rule closes the original "
        "corpus_gap finding (no longer UNKNOWN), but rule+entity+full-condition together now "
        "score HIGH (0.76), one band above this case's MEDIUM gold label. Not weight-tuned to "
        "force a match (would be tuning against a single TEST case).",
    ),
    ErrorRecord(
        category="severity_error",
        case_id="test_deductible_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="PHASE_6.5 PARTIAL: a new insurance_deductible rule closes the original "
        "corpus_gap finding (no longer UNKNOWN), but rule+entity together now score MEDIUM "
        "(0.61), not this case's LOW gold label. A deductible is itself a real cost, so MEDIUM "
        "is at least as defensible as the original LOW guess (written when no rule existed) - "
        "not weight-tuned to force a match.",
    ),
    ErrorRecord(
        category="corpus_gap",
        case_id="test_insurance_exclusion_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="STILL A GAP: a new insurance_exclusion rule exists and covers 'exclu...' wording, "
        "but this case's exact phrasing ('shall not be liable for any claim') never uses that "
        "word family, so the rule doesn't fire. Not broadened to catch 'not liable' specifically "
        "- that phrase's own 'not' risks the same self-negation trap 'waive'/'excluding' were "
        "kept out of the negation-cue list for (docs/PROVISIONAL_DECISIONS.md P6.9).",
    ),
    ErrorRecord(
        category="abstention_error",
        case_id="test_arbitration_no_condition_marker",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="STILL A GAP: an unconditional (non-conditional) arbitration clause - the rule "
        "fires alone with no entity/condition chain, landing at raw_score=0.35 (LOW band), then "
        "abstains to UNKNOWN because a bare positive rule hit isn't 'positive evidence for LOW'. "
        "No condition-marker addition can fix this (there is no connective in the text at all); "
        "the only lever is a weight/threshold change, deliberately not made since it would be "
        "justified by nothing but this one TEST case. Same structural pattern as "
        "test_standalone_jury_waiver_no_rule_coverage.",
    ),
    ErrorRecord(
        category="abstention_error",
        case_id="test_standalone_jury_waiver_no_rule_coverage",
        source="corpus/eval/datasets/risk_test_holdout.py",
        note="PHASE_6.5 PARTIAL: a new standalone_rights_waiver rule closes the original "
        "corpus_gap finding (the rule correctly fires), but with no entity and no condition "
        "connective in this text, the same structural abstention pattern as "
        "test_arbitration_no_condition_marker applies - still UNKNOWN, not MEDIUM.",
    ),
    ErrorRecord(
        category="confidence_error",
        case_id="calibration_dev_to_test_transfer",
        source="corpus/eval/run_calibration_eval.py",
        note="Isotonic calibration fit on the DEV split increases ECE on TEST (overfits a "
        "too-small sample) - do not trust the DEV-fitted mapping without a larger dataset. "
        "Unchanged by Phase 6.5 (out of scope - see docs/PROVISIONAL_DECISIONS.md).",
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
