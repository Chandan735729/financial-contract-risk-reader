"""Signal-ablation runner — Phase 6 spec SS14.

Verifies the multi-signal architecture actually adds value by re-scoring
every benchmark case with each signal knocked out (weight forced to 0) and
comparing macro F1 / HIGH precision-recall against the full engine. Reuses
`risk_engine.score_clause` and `RiskEngineConfig` directly — an ablation is
just a `RiskEngineConfig` with one or more weights zeroed, so this module
adds no new scoring logic of its own.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import DocumentType, RiskLevel  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.risk_engine import EntitySignal, score_clause  # noqa: E402
from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG, RiskEngineConfig  # noqa: E402
from app.services.risk_engine_metrics import evaluate_risk_engine  # noqa: E402


@dataclass(frozen=True, slots=True)
class AblationVariant:
    name: str
    config: RiskEngineConfig


def _zeroed(
    base: RiskEngineConfig,
    *,
    dense: bool = False,
    lexical: bool = False,
    entity: bool = False,
    condition: bool = False,
    rule: bool = False,
) -> RiskEngineConfig:
    """Returns a config with every weight zeroed except the ones named
    `True` (kept at their base value) — the inverse framing (name the
    signals to zero) reads awkwardly for combinations like "retrieval +
    entities," so callers instead name which signals survive. Explicit
    keyword arguments (not `**dict` unpacking) because `dataclasses.replace`
    validates its keyword arguments statically."""
    return replace(
        base,
        weight_dense=base.weight_dense if dense else 0.0,
        weight_lexical=base.weight_lexical if lexical else 0.0,
        weight_entity=base.weight_entity if entity else 0.0,
        weight_condition=base.weight_condition if condition else 0.0,
        weight_rule=base.weight_rule if rule else 0.0,
        # The entity-corroboration bonus (Phase 5 P5.1) only ever fires when
        # both a rule and an entity are already active — zeroed unless both
        # survive, so a single-signal variant never gets a bonus meant for
        # signal agreement it doesn't have.
        weight_corroboration=base.weight_corroboration if (entity and rule) else 0.0,
    )


def build_ablation_variants(
    base: RiskEngineConfig = DEFAULT_RISK_ENGINE_CONFIG,
) -> tuple[AblationVariant, ...]:
    return (
        AblationVariant("dense_only", _zeroed(base, dense=True)),
        AblationVariant("lexical_only", _zeroed(base, lexical=True)),
        AblationVariant("entity_only", _zeroed(base, entity=True)),
        AblationVariant("condition_only", _zeroed(base, condition=True)),
        AblationVariant("rule_only", _zeroed(base, rule=True)),
        AblationVariant("dense_plus_lexical", _zeroed(base, dense=True, lexical=True)),
        AblationVariant("retrieval_plus_entities", _zeroed(base, dense=True, lexical=True, entity=True)),
        AblationVariant(
            "retrieval_plus_entities_plus_conditions",
            _zeroed(base, dense=True, lexical=True, entity=True, condition=True),
        ),
        AblationVariant("full_engine", base),
    )


@dataclass(frozen=True, slots=True)
class AblationResult:
    variant_name: str
    macro_f1: float
    high_precision: float
    high_recall: float
    abstention_rate: float


@dataclass(frozen=True, slots=True)
class _PreparedCase:
    text: str
    matched_patterns: tuple
    entities: tuple[EntitySignal, ...]
    trigger: str | None
    condition: str | None
    consequence: str | None
    document_type: DocumentType
    low_confidence_flag: bool
    gold_level: RiskLevel


def _prepare(cases: list) -> list[_PreparedCase]:
    """Entity/condition extraction is independent of the Risk Engine's
    weights, so it is run exactly once per case here rather than once per
    ablation variant (9x fewer extraction calls)."""
    prepared: list[_PreparedCase] = []
    for case in cases:
        entities = extract_financial_entities(case.text)
        condition = extract_condition(case.text)
        entity_signals = tuple(
            EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
        )
        prepared.append(
            _PreparedCase(
                text=case.text,
                matched_patterns=tuple(case.matched_patterns),
                entities=entity_signals,
                trigger=condition.trigger,
                condition=condition.condition,
                consequence=condition.consequence,
                document_type=case.document_type,
                low_confidence_flag=case.low_confidence_flag,
                gold_level=RiskLevel(case.gold_risk_level),
            )
        )
    return prepared


def run_ablation(
    cases: list, variants: tuple[AblationVariant, ...] | None = None
) -> tuple[AblationResult, ...]:
    """`cases`: list of objects with `.text`/`.matched_patterns`/
    `.document_type`/`.low_confidence_flag`/`.gold_risk_level` — the
    `RiskBenchmarkCase` shape from
    `backend/tests/fixtures/risk_engine_benchmark.py`. Entities/condition are
    extracted here (not expected pre-populated on `cases`)."""
    variants = variants or build_ablation_variants()
    prepared = _prepare(cases)
    results: list[AblationResult] = []

    for variant in variants:
        predictions = []
        gold: list[RiskLevel] = []
        for case in prepared:
            result = score_clause(
                case.text,
                matched_patterns=list(case.matched_patterns),
                entities=list(case.entities),
                trigger=case.trigger,
                condition_text=case.condition,
                consequence=case.consequence,
                document_type=case.document_type,
                clause_low_confidence_flag=case.low_confidence_flag,
                page_number=1,
                config=variant.config,
            )
            predictions.append(result)
            gold.append(case.gold_level)

        report = evaluate_risk_engine(predictions, gold)
        results.append(
            AblationResult(
                variant_name=variant.name,
                macro_f1=report.macro_f1,
                high_precision=report.high_risk_precision,
                high_recall=report.high_risk_recall,
                abstention_rate=report.abstention_rate,
            )
        )

    return tuple(results)
