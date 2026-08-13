"""Versioned Generation Service configuration — Grounding_and_Evidence_Spec.md,
API_and_Data_Models.md SS5 ("API responses include ... model_version
(generation) ... so the frontend ... can detect when scoring logic has
changed"), same rationale as `risk_engine_config.RISK_ENGINE_VERSION`: the
model ID and prompt version are code constants, not environment-tunable
settings, so every persisted `model_version` value is reproducible from a
specific commit rather than drifting with deployment config.

**model_version state machine** (resolves a wording gap between
Grounding_and_Evidence_Spec.md SS5, which describes the fallback state's
explanation field as showing fallback *text*, and API_and_Data_Models.md
SS3, which explicitly documents the fallback state as
`explanation: null, explanation_grounded: false` — see
docs/PROVISIONAL_DECISIONS.md "Phase 7: fallback explanation field is null,
not fallback text"). Three, and only three, states ever reach a persisted
`clause_analyses` row:

  - **Skipped** (never attempted — cost control, Security_and_Privacy_v2.md
    SS8): `model_version=GENERATION_SKIPPED_MODEL_VERSION`,
    `explanation=None`, `explanation_grounded=None`. `None` (not `False`)
    for `explanation_grounded` because "not grounded" is meaningless when
    generation was never attempted — this is the one state where the
    schema's `bool | None` field is genuinely `None`.
  - **Attempted, grounded**: `model_version=MODEL_VERSION`,
    `explanation=<LLM text>`, `explanation_grounded=True`.
  - **Attempted, not shown** (grounding guard failed after the one retry,
    or the generation call itself failed): `model_version=MODEL_VERSION`
    (still worth recording which model/prompt was attempted, for the
    grounding-failure-rate metric), `explanation=None`,
    `explanation_grounded=False`. The user-facing fallback sentence
    (Grounding_and_Evidence_Spec.md SS5) is UI copy assembled client-side
    from the clause's already-present `risk_level`/`risk_category` fields,
    not backend-persisted text.
"""

from __future__ import annotations

from app.models.enums import RiskLevel

GENERATION_MODEL_ID = "claude-opus-5"
PROMPT_VERSION = "prompt_v1"

# Persisted on `clause_analyses.model_version` for any clause where
# generation was actually attempted (grounded or not) — API_and_Data_Models.md
# SS2's `model_version` column note: "Generation model + prompt version".
MODEL_VERSION = f"{GENERATION_MODEL_ID}:{PROMPT_VERSION}"

# Placeholder `model_version` for a clause where generation was never
# attempted (cost-control skip). Deliberately distinct from
# `clause_understanding_service.PENDING_MODEL_VERSION` ("unscored", meaning
# "Risk Engine has not run yet") — this means "Risk Engine has run and
# decided this clause does not get an LLM explanation," a different and
# later pipeline state.
GENERATION_SKIPPED_MODEL_VERSION = "generation_skipped"

# Risk levels that receive an LLM explanation at all (Security_and_Privacy_v2.md
# SS8 "Per-document caps ... to bound cost"; Phase 7 spec "skip LOW/UNKNOWN
# unless required"). LOW and UNKNOWN clauses are the bulk of any real
# document and their risk/evidence is already fully shown without a
# generated explanation — spending an LLM call there is the highest-volume,
# lowest-value place to cut cost. HIGH and MEDIUM are exactly the levels
# PRD_v2.md Product Principle 5 requires verified evidence for, so they are
# also the levels where a plain-language explanation adds the most value.
GENERATION_ELIGIBLE_RISK_LEVELS: frozenset[RiskLevel] = frozenset({RiskLevel.HIGH, RiskLevel.MEDIUM})
