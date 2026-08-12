"""Deterministic keyword/pattern risk rules — AI_Risk_Engine_Design.md SS3
(`rule_signal`: "a cheap, explainable, high-precision backstop independent
of the ML components"), Phase 5 spec SS15-16.

Exactly five rules, matching the Phase 5 spec's named examples — "a small,
explicit rule layer," not a general-purpose rule engine (Phase 5 spec SS15:
"Do not build an enormous rule engine in this phase"). Each rule requires a
*primary* concept term and a *secondary* risk-indicating term to co-occur
within a bounded proximity window in `clause.raw_text` — a lone keyword
never fires a rule on its own.

**Negation (Phase 5 spec SS16, non-negotiable):** a rule pairing found next
to a negation cue ("without," "no," "not," "unless," "except," ...) is
recorded with `polarity="negative"` instead of being suppressed outright —
"prepayment penalty" and "prepayment without penalty" both produce a
`RuleMatch`, but the second is explicit *evidence against* the risk
(Risk_Taxonomy_and_Labeling_Spec.md SS4 "negative example" / "confirmed
absence"), not a non-event. `risk_engine.py` uses `polarity="negative"`
matches as positive evidence for a `LOW` classification — never silently
drops them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.models.enums import RiskCategory

RULE_SET_VERSION = "risk_rules_v1"

Polarity = Literal["positive", "negative"]

# How far (in characters) from a primary-term match to look for the
# paired secondary term — wide enough to span a typical single sentence,
# narrow enough that an unrelated mention elsewhere in a long clause can't
# manufacture a false pairing.
_DEFAULT_PROXIMITY_CHARS = 120

# Negation cues that flip a rule pairing from "risky" to "confirmed safe."
# Deliberately excludes "waive(d)" — that word is itself the *positive*
# secondary term for the arbitration_waiver rule, so including it here would
# make that rule permanently self-negate.
_NEGATION_CUES = re.compile(r"\b(?:without|no|not|n't|never|excluding|except|unless)\b", re.IGNORECASE)
# How far around the matched pairing to look for a negation cue.
_NEGATION_WINDOW_BEFORE = 40
_NEGATION_WINDOW_AFTER = 10


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    risk_category: RiskCategory
    risk_subcategory: str
    polarity: Polarity
    evidence_text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class _RuleDefinition:
    rule_id: str
    risk_category: RiskCategory
    risk_subcategory: str
    primary: re.Pattern[str]
    secondary: re.Pattern[str]
    proximity_chars: int = _DEFAULT_PROXIMITY_CHARS
    # PROVISIONAL_V2 (docs/PROVISIONAL_DECISIONS.md "Phase 5: auto_renewal_notice
    # is negation-insensitive"): `auto_renewal_notice`'s secondary term
    # ("notice") is not itself the risky element the way "penalty"/"fee" are
    # for the other rules — it is the escape-mechanism half of the risk
    # pattern's *canonical* phrasing ("renews automatically unless notice is
    # given," Risk_Taxonomy_and_Labeling_Spec.md SS1.3 `auto_renewal`).
    # Treating "unless" as a negation cue there would flip almost every
    # real-world instance of this exact MEDIUM-risk pattern to "confirmed
    # safe," which is backwards.
    negation_sensitive: bool = True


# Phase 5 spec SS15's five named examples, in order.
_RULES: tuple[_RuleDefinition, ...] = (
    _RuleDefinition(
        rule_id="arbitration_waiver",
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="arbitration",
        primary=re.compile(r"\barbitrat\w*\b", re.IGNORECASE),
        secondary=re.compile(r"\bwaiv(?:e|es|ed|er|ers|ing)\b", re.IGNORECASE),
    ),
    _RuleDefinition(
        rule_id="prepayment_penalty",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        primary=re.compile(
            r"\bprepay\w*\b|\bpre-payment\w*\b|\bpays?\s+off\s+early\b|\brepaid\s+in\s+full\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(r"\bpenalt(?:y|ies)\b|\bcharges?\b|\bfees?\b", re.IGNORECASE),
    ),
    _RuleDefinition(
        rule_id="auto_renewal_notice",
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="auto_renewal",
        primary=re.compile(
            r"\bautomatically\s+renew\w*\b|\bauto-renew\w*\b|\brenews?\s+automatically\b", re.IGNORECASE
        ),
        secondary=re.compile(r"\bnotice\b", re.IGNORECASE),
        negation_sensitive=False,
    ),
    _RuleDefinition(
        rule_id="missed_payment_acceleration",
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="acceleration",
        primary=re.compile(
            r"\bmissed?\s+payment\w*\b|\blate\s+payment\w*\b|\bfail(?:s|ure)?\s+to\s+pay\b|\bdefault\w*\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(
            r"\baccelerat\w*\b|\bimmediately\s+due\b|\bentire\s+(?:outstanding\s+)?balance\b",
            re.IGNORECASE,
        ),
    ),
    _RuleDefinition(
        rule_id="early_termination_fee",
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="early_termination_fee",
        primary=re.compile(
            r"\bearly\s+termination\b|\bterminat\w*\s+(?:this\s+agreement\s+|the\s+agreement\s+)?before\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(r"\bfees?\b|\bcharges?\b|\bpenalt(?:y|ies)\b", re.IGNORECASE),
    ),
)


def _has_negation(text: str, window_start: int, window_end: int) -> bool:
    window = text[max(0, window_start) : min(len(text), window_end)]
    return _NEGATION_CUES.search(window) is not None


def evaluate_rules(clause_text: str) -> list[RuleMatch]:
    """Deterministic, explainable, versioned. Never raises on unusual input —
    a rule that doesn't find its pairing simply doesn't fire. At most one
    `RuleMatch` per rule (the first qualifying pairing found), so a clause
    that repeats the same risky phrase several times doesn't inflate
    `rule_boost` beyond a single hit's worth of signal.
    """
    matches: list[RuleMatch] = []
    for rule in _RULES:
        for primary_match in rule.primary.finditer(clause_text):
            window_start = max(0, primary_match.start() - rule.proximity_chars)
            window_end = min(len(clause_text), primary_match.end() + rule.proximity_chars)
            window_text = clause_text[window_start:window_end]
            secondary_match = rule.secondary.search(window_text)
            if secondary_match is None:
                continue

            secondary_start = window_start + secondary_match.start()
            secondary_end = window_start + secondary_match.end()
            span_start = min(primary_match.start(), secondary_start)
            span_end = max(primary_match.end(), secondary_end)
            negated = rule.negation_sensitive and _has_negation(
                clause_text,
                span_start - _NEGATION_WINDOW_BEFORE,
                span_end + _NEGATION_WINDOW_AFTER,
            )
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    risk_category=rule.risk_category,
                    risk_subcategory=rule.risk_subcategory,
                    polarity="negative" if negated else "positive",
                    evidence_text=clause_text[span_start:span_end],
                    start_char=span_start,
                    end_char=span_end,
                )
            )
            break  # one pairing is enough signal for this rule; stop scanning it
    return matches
