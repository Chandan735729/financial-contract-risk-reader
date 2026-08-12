"""Abstention (UNKNOWN) evaluation metrics — Phase 6 spec SS10.

`gold_expected_abstention[i]` is whether a *correctly-working* system
should abstain on sample `i` (`ClauseGroundTruth.expected_abstention`).
`gold_ambiguous[i]` is whether the clause is genuinely ambiguous
(`ClauseGroundTruth.ambiguous`) — used to answer the phase brief's own
question: "are genuinely ambiguous clauses more likely to become UNKNOWN,
or is UNKNOWN simply used because the engine is under-confident
everywhere?" (`ambiguity_capture_rate` vs. `false_abstention_rate`, read
together, answer this.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AbstentionEvalReport:
    sample_count: int
    unknown_precision: float  # of predicted UNKNOWN, how many were gold-expected to abstain
    unknown_recall: float  # of gold-expected-abstain, how many were predicted UNKNOWN
    abstention_rate: float  # fraction of all samples predicted UNKNOWN
    false_abstention_rate: float  # of gold-should-NOT-abstain samples, how many were predicted UNKNOWN anyway
    ambiguity_capture_rate: float  # of genuinely-ambiguous gold samples, how many were predicted UNKNOWN


@dataclass(frozen=True, slots=True)
class AbstentionByCategory:
    key: str
    abstention_rate: float
    sample_count: int


def evaluate_abstention(
    predicted_unknown: list[bool],
    gold_expected_abstention: list[bool],
    gold_ambiguous: list[bool],
) -> AbstentionEvalReport:
    n = len(predicted_unknown)
    if not (len(gold_expected_abstention) == n and len(gold_ambiguous) == n):
        raise ValueError("all input lists must be the same length")
    if n == 0:
        return AbstentionEvalReport(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    tp = sum(1 for p, g in zip(predicted_unknown, gold_expected_abstention, strict=True) if p and g)
    fp = sum(1 for p, g in zip(predicted_unknown, gold_expected_abstention, strict=True) if p and not g)
    fn = sum(1 for p, g in zip(predicted_unknown, gold_expected_abstention, strict=True) if not p and g)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    abstention_rate = sum(predicted_unknown) / n

    should_not_abstain = [not g for g in gold_expected_abstention]
    should_not_abstain_count = sum(should_not_abstain)
    false_abstentions = sum(1 for p, s in zip(predicted_unknown, should_not_abstain, strict=True) if p and s)
    false_abstention_rate = (
        (false_abstentions / should_not_abstain_count) if should_not_abstain_count > 0 else 0.0
    )

    ambiguous_count = sum(gold_ambiguous)
    ambiguous_captured = sum(1 for p, a in zip(predicted_unknown, gold_ambiguous, strict=True) if p and a)
    ambiguity_capture_rate = (ambiguous_captured / ambiguous_count) if ambiguous_count > 0 else 0.0

    return AbstentionEvalReport(
        sample_count=n,
        unknown_precision=precision,
        unknown_recall=recall,
        abstention_rate=abstention_rate,
        false_abstention_rate=false_abstention_rate,
        ambiguity_capture_rate=ambiguity_capture_rate,
    )


def abstention_by_group(predicted_unknown: list[bool], groups: list[str]) -> tuple[AbstentionByCategory, ...]:
    if len(predicted_unknown) != len(groups):
        raise ValueError("predicted_unknown and groups must be the same length")
    by_group: dict[str, list[bool]] = {}
    for p, g in zip(predicted_unknown, groups, strict=True):
        by_group.setdefault(g, []).append(p)
    return tuple(
        AbstentionByCategory(key=g, abstention_rate=sum(vals) / len(vals), sample_count=len(vals))
        for g, vals in sorted(by_group.items())
    )
