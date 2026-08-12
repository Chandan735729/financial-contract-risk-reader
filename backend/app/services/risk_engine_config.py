"""Versioned Risk Engine configuration — AI_Risk_Engine_Design.md SS4/SS8,
Phase 5 spec SS8 ("Weights must not be scattered throughout code. Create a
versioned configuration object.").

`RiskEngineConfig.version` is persisted on every scored `clause_analyses`
row (`engine_version` column, API_and_Data_Models.md SS2) so a report can
always be traced back to the exact weights/thresholds that produced it.

**PROVISIONAL_V2** (see docs/PROVISIONAL_DECISIONS.md "Phase 5: initial
engine weights and thresholds"): the numeric values below are
domain-reasoned starting points, not fit against a labeled benchmark — no
such benchmark exists yet (Dataset_and_Evaluation_Spec.md SS4 is real-world,
still open work). `weight_rule` and `weight_entity` are each individually
>= `weight_dense` (AI_Risk_Engine_Design.md SS4: "rule hits and entity
strength weighted comparably to or above raw similarity, per Product
Principle 2"). Every weight/threshold change must be re-run against
`corpus/eval/run_risk_engine_eval.py` before merge (Phase 5 spec SS27,
AI_Risk_Engine_Design.md SS7 "Weight misconfiguration").
"""

from __future__ import annotations

from dataclasses import dataclass

RISK_ENGINE_VERSION = "risk_engine_v1"


@dataclass(frozen=True, slots=True)
class RiskEngineConfig:
    version: str = RISK_ENGINE_VERSION

    # Step 2 — weighted combination (AI_Risk_Engine_Design.md SS4).
    # Sums to 1.0 so `raw_risk_score` before the doc_type_relevance gate is
    # already bounded to [0, 1] when every signal is maxed.
    weight_dense: float = 0.10
    weight_lexical: float = 0.05
    weight_entity: float = 0.20
    weight_condition: float = 0.10
    weight_rule: float = 0.35
    # `weight_corroboration` rewards a rule hit *and* a supporting financial
    # entity co-occurring — the explicit severity rule from
    # Risk_Taxonomy_and_Labeling_Spec.md SS2: "a prepayment_penalty with an
    # extracted 5% reads HIGH; with no extractable amount ... it may read
    # MEDIUM." Zero when either signal is absent (see
    # `risk_engine.RiskSignals.corroboration`), so a rule hit alone still
    # only reaches MEDIUM.
    weight_corroboration: float = 0.20

    # Step 3 — risk-level thresholds (banded, with a genuine "no decision"
    # zone below `low_threshold` — AI_Risk_Engine_Design.md SS4 Step 3).
    high_threshold: float = 0.70
    medium_threshold: float = 0.45
    low_threshold: float = 0.20

    # Step 6 — abstention. A LOW-band score with confidence below this floor
    # is abstained rather than shown (AI_Risk_Engine_Design.md SS6, first
    # bullet: "ambiguous band ... and confidence_score is below
    # CONFIDENCE_FLOOR").
    confidence_floor: float = 0.50

    # Step 4 — confidence combination weights (AI_Risk_Engine_Design.md SS4
    # `g()`). Sums to 1.0. `confidence_heuristic, not yet calibrated`
    # (Phase 5 spec SS13) — see `risk_engine.apply_calibration` for the
    # explicit calibration hook this is designed to be replaced through.
    confidence_weight_agreement: float = 0.35
    confidence_weight_evidence: float = 0.30
    confidence_weight_condition: float = 0.15
    confidence_weight_margin: float = 0.20

    confidence_high_threshold: float = 0.75
    confidence_medium_threshold: float = 0.50

    def __post_init__(self) -> None:
        weights = (
            self.weight_dense,
            self.weight_lexical,
            self.weight_entity,
            self.weight_condition,
            self.weight_rule,
            self.weight_corroboration,
        )
        if any(w < 0 for w in weights):
            raise ValueError("RiskEngineConfig scoring weights must be non-negative")
        if not (self.high_threshold > self.medium_threshold > self.low_threshold >= 0):
            raise ValueError(
                "RiskEngineConfig thresholds must satisfy "
                "high_threshold > medium_threshold > low_threshold >= 0"
            )
        if self.high_threshold > 1.0:
            raise ValueError("RiskEngineConfig high_threshold must be <= 1.0")
        if not (self.confidence_high_threshold > self.confidence_medium_threshold >= 0):
            raise ValueError(
                "RiskEngineConfig confidence_high_threshold must be > " "confidence_medium_threshold >= 0"
            )
        if not (0.0 <= self.confidence_floor <= 1.0):
            raise ValueError("RiskEngineConfig confidence_floor must be in [0, 1]")


DEFAULT_RISK_ENGINE_CONFIG = RiskEngineConfig()
