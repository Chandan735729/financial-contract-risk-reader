"""Risk Engine — AI_Risk_Engine_Design.md SS4-SS6, Phase 5 spec SS5-17.

**Deterministic, versioned, multi-signal.** Never a single similarity
threshold, never an LLM judgment call (Phase 5 spec header; module contains
no network/model call of any kind). Function names below deliberately mirror
`AI_Risk_Engine_Design.md` SS5's pseudocode (`score_entities`,
`score_conditions`, `check_rules` -> `risk_rules.evaluate_rules`,
`category_doc_type_relevance`, `calibrated_confidence`, `threshold_to_level`,
`apply_abstention_rules`) so the implementation stays traceable to the
design doc line by line.

**Confidence heuristic, not yet calibrated** (Phase 5 spec SS13): a proper
isotonic-regression fit requires a labeled held-out dev split
(Dataset_and_Evaluation_Spec.md SS6); only a synthetic development benchmark
exists so far (`corpus/eval/run_risk_engine_eval.py`). `apply_calibration`
is the explicit hook this will be replaced through once real labeled data
exists — see docs/PROVISIONAL_DECISIONS.md "Phase 5: confidence heuristic".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.models.enums import ConfidenceLevel, DocumentType, RiskCategory, RiskLevel
from app.services.evidence_engine import EvidenceResult, assemble_and_verify_evidence
from app.services.retrieval_service import is_category_applicable
from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG, RiskEngineConfig
from app.services.risk_rules import RuleMatch, evaluate_rules

ConditionCompletenessLabel = Literal["none", "partial", "full"]


# ==================================================================
# Adapters — decouple this module from Phase 4's ORM/extractor-specific
# shapes (Phase 5 spec SS6: "Keep these inputs separately inspectable. Do
# not merge them earlier in the pipeline."). `risk_scoring_service.py`
# builds these from the persisted `clause_analyses` row's children.
# ==================================================================


class EntityLike(Protocol):
    """Read-only (property-based) Protocol members — a plain mutable-attribute
    Protocol cannot be structurally satisfied by a frozen dataclass (PEP 544
    read/write attribute variance), and `EntitySignal`/`PatternSignal` below
    are deliberately immutable."""

    @property
    def entity_type(self) -> str: ...
    @property
    def value(self) -> str: ...
    @property
    def raw_text(self) -> str: ...
    @property
    def start_char(self) -> int: ...
    @property
    def end_char(self) -> int: ...


@dataclass(frozen=True, slots=True)
class EntitySignal:
    entity_type: str
    value: str
    raw_text: str
    start_char: int
    end_char: int


class PatternLike(Protocol):
    @property
    def similarity_score(self) -> float: ...
    @property
    def lexical_score(self) -> float: ...
    @property
    def risk_category(self) -> RiskCategory | None: ...
    @property
    def risk_subcategory(self) -> str | None: ...
    @property
    def is_negative_example(self) -> bool: ...
    @property
    def taxonomy_version(self) -> str: ...
    @property
    def corpus_version(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PatternSignal:
    similarity_score: float
    lexical_score: float
    risk_category: RiskCategory | None
    risk_subcategory: str | None
    is_negative_example: bool
    taxonomy_version: str
    corpus_version: str


# ==================================================================
# Candidate signal vector (AI_Risk_Engine_Design.md SS4 Step 1) — every
# component kept as its own field, never pre-merged.
# ==================================================================


@dataclass(frozen=True, slots=True)
class RiskSignals:
    dense_similarity: float
    lexical_score: float
    entity_strength: float
    condition_completeness_score: float
    condition_completeness_label: ConditionCompletenessLabel
    rule_hit: bool
    rule_boost: float
    rule_matches: tuple[RuleMatch, ...]
    candidate_category: RiskCategory | None
    candidate_subcategory: str | None
    doc_type_relevance: float
    retrieval_margin: float
    signal_agreement: float
    corroboration: float
    has_positive_low_evidence: bool


@dataclass(frozen=True, slots=True)
class RiskResult:
    risk_level: RiskLevel
    risk_score: float
    risk_category: RiskCategory | None
    risk_subcategory: str | None
    confidence_level: ConfidenceLevel
    confidence_score: float
    abstained: bool
    abstain_reason: str | None
    engine_version: str
    signals: RiskSignals
    evidence: EvidenceResult


# ==================================================================
# Non-retrieval signal scoring (AI_Risk_Engine_Design.md SS3)
# ==================================================================

# PROVISIONAL_V2 — domain-reasoned entity-type weights, not fit against a
# labeled benchmark (see docs/PROVISIONAL_DECISIONS.md). `rate`/`fee` weigh
# more than a bare `amount`/`percentage` because they more directly name a
# recurring cost, matching Risk_Taxonomy_and_Labeling_Spec.md SS2's example
# ("a prepayment_penalty with an extracted 5% reads HIGH").
_ENTITY_TYPE_BASE_WEIGHT: dict[str, float] = {
    "rate": 0.45,
    "fee": 0.45,
    "percentage": 0.35,
    "amount": 0.30,
    "time_period": 0.15,
}
_ENTITY_MAGNITUDE_BONUS = 0.10
_ENTITY_MAGNITUDE_MIN_VALUE = 1.0


def score_entities(entities: Sequence[EntityLike]) -> float:
    """Presence and magnitude of extracted financial entities
    (AI_Risk_Engine_Design.md SS3 `entity_signal`). A bare `percentage`/
    `rate` entity with a non-trivial numeric value gets a small magnitude
    bonus over a merely-detected one, per Risk_Taxonomy_and_Labeling_Spec.md
    SS2 ("presence and magnitude ... a detected 5% ... is a stronger signal
    than an amount-free mention")."""
    if not entities:
        return 0.0
    score = 0.0
    for entity in entities:
        score += _ENTITY_TYPE_BASE_WEIGHT.get(entity.entity_type, 0.10)
        if entity.entity_type in ("percentage", "rate"):
            try:
                numeric_value = float(entity.value)
            except ValueError:
                numeric_value = 0.0
            if numeric_value >= _ENTITY_MAGNITUDE_MIN_VALUE:
                score += _ENTITY_MAGNITUDE_BONUS
    return max(0.0, min(1.0, score))


def score_conditions(
    *, trigger: str | None, condition_text: str | None, consequence: str | None
) -> tuple[float, ConditionCompletenessLabel]:
    """Completeness of the trigger->condition->consequence chain
    (AI_Risk_Engine_Design.md SS3 `condition_signal`) — completeness raises
    *confidence*, not severity directly (Risk_Taxonomy_and_Labeling_Spec.md
    SS2). `full` requires both ends of the chain (trigger and consequence);
    a bare `condition` qualifier alone (no trigger, no consequence) is only
    `partial`."""
    has_trigger = bool(trigger)
    has_consequence = bool(consequence)
    if has_trigger and has_consequence:
        return 1.0, "full"
    if has_trigger or has_consequence or bool(condition_text):
        return 0.5, "partial"
    return 0.0, "none"


def category_doc_type_relevance(category: RiskCategory | None, document_type: DocumentType) -> float:
    """Multiplicative gate (AI_Risk_Engine_Design.md SS4 Step 2: "doc_type_relevance
    ... multiplicative gate, not additive"). Reuses
    `retrieval_service.is_category_applicable` — the same taxonomy
    applicability table (Risk_Taxonomy_and_Labeling_Spec.md SS1) must not be
    duplicated/redefined at the scoring layer. `document_type=UNKNOWN` or no
    candidate category never triggers a hard block (Phase 5 spec SS14: "do
    not apply unjustified hard risk assumptions")."""
    if category is None:
        return 1.0
    return 1.0 if is_category_applicable(category, document_type) else 0.0


def retrieval_margin(matched_patterns: Sequence[PatternLike]) -> float:
    """Gap between the top match and the next-best match
    (AI_Risk_Engine_Design.md SS4 Step 4: "a narrow margin lowers confidence
    even if the top score is high"). A single, uncontested match is treated
    as maximally unambiguous (full credit); no matches contribute nothing."""
    if not matched_patterns:
        return 0.0
    scores = sorted((max(m.similarity_score, m.lexical_score) for m in matched_patterns), reverse=True)
    if len(scores) == 1:
        return scores[0]
    return max(0.0, scores[0] - scores[1])


_AGREEMENT_ACTIVATION_DENSE = 0.30
_AGREEMENT_ACTIVATION_LEXICAL = 0.10
_AGREEMENT_CONFLICT_PENALTY = 0.5


def compute_signal_agreement(
    *, dense: float, lexical: float, entity_strength: float, rule_matches: Sequence[RuleMatch]
) -> float:
    """Do dense/lexical/rule/entity signals agree or conflict
    (AI_Risk_Engine_Design.md SS4 Step 4 `signal_agreement`)? Counted as the
    fraction of independently-active signals — a rule firing at all (either
    polarity) counts as one active, unambiguous signal, since a clean
    negation match ("prepayment without penalty") is just as much a
    confident finding as a positive one. Halved when a *negative* rule match
    coexists with strong positive signal elsewhere (high dense similarity or
    a separate positive rule) — that combination is a genuine conflict, not
    mere silence."""
    positive_rule = any(m.polarity == "positive" for m in rule_matches)
    negative_rule = any(m.polarity == "negative" for m in rule_matches)
    rule_fired = positive_rule or negative_rule
    active = sum(
        (
            dense >= _AGREEMENT_ACTIVATION_DENSE,
            lexical >= _AGREEMENT_ACTIVATION_LEXICAL,
            entity_strength > 0.0,
            rule_fired,
        )
    )
    agreement = active / 4
    if negative_rule and (dense >= 0.5 or positive_rule):
        agreement *= _AGREEMENT_CONFLICT_PENALTY
    return max(0.0, min(1.0, agreement))


def evidence_completeness(evidence: EvidenceResult) -> float:
    """How many/how strong the evidence spans are
    (AI_Risk_Engine_Design.md SS4 Step 4 `evidence_completeness`) — the
    fraction of assembled evidence candidates that actually verified."""
    total = len(evidence.verified) + evidence.unverifiable_count
    if total == 0:
        return 0.0
    return len(evidence.verified) / total


def apply_calibration(raw_confidence: float) -> float:
    """Explicit calibration hook (Phase 5 spec SS13). Identity mapping until
    a labeled dev split (Dataset_and_Evaluation_Spec.md SS6) exists to fit an
    isotonic-regression mapping from raw to calibrated confidence — do not
    claim calibration before that fit happens (Phase 5 spec SS13)."""
    return raw_confidence


def calibrated_confidence(
    config: RiskEngineConfig,
    *,
    signal_agreement_score: float,
    evidence_completeness_score: float,
    condition_completeness_score: float,
    retrieval_margin_score: float,
) -> float:
    raw = (
        config.confidence_weight_agreement * signal_agreement_score
        + config.confidence_weight_evidence * evidence_completeness_score
        + config.confidence_weight_condition * condition_completeness_score
        + config.confidence_weight_margin * retrieval_margin_score
    )
    # Same IEEE-754 summation-artifact rounding as `score_clause`'s raw_score.
    return apply_calibration(round(max(0.0, min(1.0, raw)), 6))


def confidence_to_level(confidence_score: float, config: RiskEngineConfig) -> ConfidenceLevel:
    if confidence_score >= config.confidence_high_threshold:
        return ConfidenceLevel.HIGH
    if confidence_score >= config.confidence_medium_threshold:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def threshold_to_level(raw_score: float, config: RiskEngineConfig) -> RiskLevel:
    """AI_Risk_Engine_Design.md SS4 Step 3 — banded thresholding with a
    genuine "no decision" zone below `low_threshold` (`RiskLevel.UNKNOWN` is
    the candidate level there, not a fallback bolted on afterward)."""
    if raw_score >= config.high_threshold:
        return RiskLevel.HIGH
    if raw_score >= config.medium_threshold:
        return RiskLevel.MEDIUM
    if raw_score >= config.low_threshold:
        return RiskLevel.LOW
    return RiskLevel.UNKNOWN


# ==================================================================
# Abstention (AI_Risk_Engine_Design.md SS6, Phase 5 spec SS11/SS17)
# ==================================================================


def apply_abstention_rules(
    candidate_level: RiskLevel,
    confidence_score: float,
    *,
    clause_low_confidence_flag: bool,
    verified_evidence_present: bool,
    has_positive_low_evidence: bool,
    config: RiskEngineConfig,
) -> tuple[RiskLevel, bool, str | None]:
    """Returns `(final_level, abstained, abstain_reason)`. Every abstention
    path is explicit and documented — never a silent fallback
    (AI_Risk_Engine_Design.md SS6 header)."""

    if clause_low_confidence_flag:
        return (
            RiskLevel.UNKNOWN,
            True,
            "Segmentation confidence for this clause is low; an unreliable clause "
            "boundary undermines any risk judgment about it.",
        )

    if candidate_level in (RiskLevel.HIGH, RiskLevel.MEDIUM) and not verified_evidence_present:
        return (
            RiskLevel.UNKNOWN,
            True,
            f"Signals indicated {candidate_level.value} risk, but no verified evidence "
            "span supports the decision; a risk judgment without verifiable evidence "
            "is not shown as confident (Grounding_and_Evidence_Spec.md SS2).",
        )

    if candidate_level == RiskLevel.LOW:
        # This is literally "the ambiguous band between LOW_THRESHOLD and
        # MEDIUM_THRESHOLD" (AI_Risk_Engine_Design.md SS6, first bullet) —
        # a real, non-trivial raw_score landed here, so a low-confidence
        # result in this band is abstained rather than shown.
        if not has_positive_low_evidence:
            return (
                RiskLevel.UNKNOWN,
                True,
                "No retrieval, rule, or entity signal provides positive evidence for a "
                "low-risk classification; absence of a match is not treated as safe "
                "(no retrieval match != low risk).",
            )
        if confidence_score < config.confidence_floor:
            return (
                RiskLevel.UNKNOWN,
                True,
                "Risk score falls in the low-confidence ambiguous band and confidence "
                "is below the supported threshold for a low-risk classification.",
            )
        return RiskLevel.LOW, False, None

    if candidate_level == RiskLevel.UNKNOWN:
        # Below `low_threshold` entirely (near-zero score) is a different
        # situation from the ambiguous LOW band above: an explicit
        # negative-example/negated-rule finding here is a definitive,
        # high-precision determination on its own — Risk_Taxonomy_and_Labeling_Spec.md
        # SS4's "confirmed absence" — so it is not additionally gated on
        # `confidence_floor` (confidence is still computed and reported
        # independently; it may legitimately be low).
        if has_positive_low_evidence:
            return RiskLevel.LOW, False, None
        return (
            RiskLevel.UNKNOWN,
            True,
            "Insufficient signal (retrieval, rule, or extractable entity) to classify "
            "this clause with confidence.",
        )

    return candidate_level, False, None


# ==================================================================
# Candidate category selection
# ==================================================================


def _select_candidate_category(
    rule_matches: Sequence[RuleMatch], matched_patterns: Sequence[PatternLike]
) -> tuple[RiskCategory | None, str | None]:
    positive_rules = [m for m in rule_matches if m.polarity == "positive"]
    if positive_rules:
        top_rule = positive_rules[0]
        return top_rule.risk_category, top_rule.risk_subcategory
    if matched_patterns:
        top_pattern = max(matched_patterns, key=lambda m: max(m.similarity_score, m.lexical_score))
        if top_pattern.risk_category is not None:
            return top_pattern.risk_category, top_pattern.risk_subcategory
    return None, None


def _validate_pattern_versions(matched_patterns: Sequence[PatternLike]) -> None:
    """Corpus/taxonomy versioning (AI_Risk_Engine_Design.md SS2, SS7 "Corpus/
    taxonomy version mismatch ... halts scoring for that clause with a clear
    internal error"). Raises rather than silently mixing — a component
    failure, not something abstention should quietly absorb (Phase 5 spec
    SS11: "Do not use UNKNOWN merely because a component crashed")."""
    versions = {(m.taxonomy_version, m.corpus_version) for m in matched_patterns}
    if len(versions) > 1:
        raise ValueError(
            "Risk Engine received matched_patterns spanning multiple taxonomy/corpus "
            f"versions in one scoring run: {sorted(versions)} — refusing to mix them "
            "(AI_Risk_Engine_Design.md SS2/SS7)."
        )


# ==================================================================
# End-to-end scoring (AI_Risk_Engine_Design.md SS5 pseudocode)
# ==================================================================


def score_clause(
    clause_raw_text: str,
    *,
    matched_patterns: Sequence[PatternLike],
    entities: Sequence[EntityLike],
    trigger: str | None,
    condition_text: str | None,
    consequence: str | None,
    document_type: DocumentType,
    clause_low_confidence_flag: bool,
    page_number: int | None,
    config: RiskEngineConfig = DEFAULT_RISK_ENGINE_CONFIG,
) -> RiskResult:
    """One clause in, one `RiskResult` out. Never calls an LLM, never makes a
    network call, deterministic for identical inputs (Phase 5 spec header,
    SS25)."""
    _validate_pattern_versions(matched_patterns)

    rule_matches = evaluate_rules(clause_raw_text)
    evidence = assemble_and_verify_evidence(
        clause_raw_text,
        page_number=page_number,
        entities=entities,
        trigger=trigger,
        condition_text=condition_text,
        consequence=consequence,
        rule_matches=rule_matches,
    )

    dense = max((m.similarity_score for m in matched_patterns), default=0.0)
    lexical = max((m.lexical_score for m in matched_patterns), default=0.0)
    entity_strength = score_entities(entities)
    condition_score, condition_label = score_conditions(
        trigger=trigger, condition_text=condition_text, consequence=consequence
    )

    positive_rules = [m for m in rule_matches if m.polarity == "positive"]
    negative_rules = [m for m in rule_matches if m.polarity == "negative"]
    rule_hit = bool(positive_rules)
    rule_boost = 1.0 if rule_hit else 0.0

    candidate_category, candidate_subcategory = _select_candidate_category(rule_matches, matched_patterns)
    doc_relevance = category_doc_type_relevance(candidate_category, document_type)

    # Risk_Taxonomy_and_Labeling_Spec.md SS2: "a prepayment_penalty with an
    # extracted 5% reads HIGH; with no extractable amount ... it may read
    # MEDIUM." A rule hit alone (no corroborating entity) is deliberately
    # capped below HIGH by `weight_rule` on its own; this bonus only applies
    # when a positive rule *and* a real financial entity both fired.
    corroboration = 1.0 if (rule_hit and entity_strength > 0.0) else 0.0

    raw_score = (
        config.weight_dense * dense
        + config.weight_lexical * lexical
        + config.weight_entity * entity_strength
        + config.weight_condition * condition_score
        + config.weight_rule * rule_boost
        + config.weight_corroboration * corroboration
    ) * doc_relevance
    # Rounded to avoid IEEE-754 summation artifacts (e.g. 0.1 + 0.35 ==
    # 0.44999999999999996 in binary float) landing a clause a hair below a
    # threshold it should exactly meet.
    raw_score = round(max(0.0, min(1.0, raw_score)), 6)

    margin = retrieval_margin(matched_patterns)
    agreement = compute_signal_agreement(
        dense=dense, lexical=lexical, entity_strength=entity_strength, rule_matches=rule_matches
    )
    evidence_complete = evidence_completeness(evidence)

    confidence_score = calibrated_confidence(
        config,
        signal_agreement_score=agreement,
        evidence_completeness_score=evidence_complete,
        condition_completeness_score=condition_score,
        retrieval_margin_score=margin,
    )
    confidence_level = confidence_to_level(confidence_score, config)

    has_positive_low_evidence = bool(negative_rules) or any(m.is_negative_example for m in matched_patterns)
    verified_evidence_present = len(evidence.verified) > 0

    candidate_level = threshold_to_level(raw_score, config)
    final_level, abstained, abstain_reason = apply_abstention_rules(
        candidate_level,
        confidence_score,
        clause_low_confidence_flag=clause_low_confidence_flag,
        verified_evidence_present=verified_evidence_present,
        has_positive_low_evidence=has_positive_low_evidence,
        config=config,
    )

    # UNKNOWN carries no meaningful severity score (Phase 4 precedent:
    # get_or_create_pending_analysis uses risk_score=0.0 for the analogous
    # "not confidently scored" state) — an abstained clause never displays a
    # score that looks like a hidden, suppressed risk judgment.
    final_score = 0.0 if abstained else raw_score

    signals = RiskSignals(
        dense_similarity=dense,
        lexical_score=lexical,
        entity_strength=entity_strength,
        condition_completeness_score=condition_score,
        condition_completeness_label=condition_label,
        rule_hit=rule_hit,
        rule_boost=rule_boost,
        rule_matches=tuple(rule_matches),
        candidate_category=candidate_category,
        candidate_subcategory=candidate_subcategory,
        doc_type_relevance=doc_relevance,
        retrieval_margin=margin,
        signal_agreement=agreement,
        corroboration=corroboration,
        has_positive_low_evidence=has_positive_low_evidence,
    )

    return RiskResult(
        risk_level=final_level,
        risk_score=final_score,
        risk_category=candidate_category,
        risk_subcategory=candidate_subcategory,
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        abstained=abstained,
        abstain_reason=abstain_reason,
        engine_version=config.version,
        signals=signals,
        evidence=evidence,
    )
