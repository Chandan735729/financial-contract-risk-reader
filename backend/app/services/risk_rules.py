"""Deterministic keyword/pattern risk rules — AI_Risk_Engine_Design.md SS3
(`rule_signal`: "a cheap, explainable, high-precision backstop independent
of the ML components"), Phase 5 spec SS15-16.

Phase 5 spec SS15's five named examples, plus 8 more added in PHASE_6.5
(docs/PROVISIONAL_DECISIONS.md P6.6 item 5 — whole taxonomy categories had
zero rule coverage) — 13 total, still "a small, explicit rule layer," not a
general-purpose rule engine (Phase 5 spec SS15: "Do not build an enormous
rule engine in this phase"). Each rule requires a *primary* concept term and
a *secondary* risk-indicating term to co-occur within a bounded proximity
window in `clause.raw_text` — a lone keyword never fires a rule on its own.

**Negation (Phase 5 spec SS16, non-negotiable):** a rule pairing found next
to a negation cue ("without," "no," "not," "neither," ...) is recorded with
`polarity="negative"` instead of being suppressed outright — "prepayment
penalty" and "prepayment without penalty" both produce a `RuleMatch`, but the
second is explicit *evidence against* the risk (Risk_Taxonomy_and_Labeling_Spec.md
SS4 "negative example" / "confirmed absence"), not a non-event. `risk_engine.py`
uses `polarity="negative"` matches as positive evidence for a `LOW`
classification — never silently drops them.

**Conditional exceptions (PHASE_6.5, docs/PROVISIONAL_DECISIONS.md P6.9):**
"unless"/"except" are deliberately *not* treated as simple negation cues —
"No prepayment penalty applies unless the loan is repaid within 12 months"
is not "confirmed safe"; the risk is conditionally re-established by the
exception. A pairing that is simple-negated *and* followed by an
`_EXCEPTION_MARKERS` hit gets `polarity="conditional"` instead of
`"negative"` — still risk-bearing (treated like `"positive"` for scoring),
but distinct on `RuleMatch` for evidence/explanation. See P6.9 for why this
was the smallest viable schema extension over inventing a larger structured
"exception" shape.

**Severity ceiling (PHASE_6.6, docs/PROVISIONAL_DECISIONS.md P6.10):**
Risk_Taxonomy_and_Labeling_Spec.md SS1 gives each subcategory a *default
severity band* — some subcategories are flat-MEDIUM or LOW–MEDIUM banded,
never MEDIUM–HIGH or HIGH. The scoring formula in `risk_engine.py` has no
notion of *which* category it's scoring — the same rule/entity/condition
combination formula applies uniformly regardless of subcategory, so a
flat-MEDIUM category with strong entity+condition signal can currently
reach HIGH (empirically confirmed: a fee-heavy `auto_renewal_notice` match
scores 0.83/HIGH even though `auto_renewal`'s taxonomy band tops out at
MEDIUM). `severity_ceiling` on a rule caps the *final* level at the
subcategory's taxonomy-stated upper band — applied post-threshold, so it
only ever lowers an already-computed level, never raises one. This cannot
introduce a false negative (a genuinely LOW/UNKNOWN case is unaffected) and
cannot regress any currently-passing case (no currently-passing DEV/TEST/
adversarial case is *correctly* HIGH for one of the ceiling-bearing
subcategories — see P6.10 for the full verification).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.models.enums import RiskCategory, RiskLevel

RULE_SET_VERSION = "risk_rules_v1"

Polarity = Literal["positive", "negative", "conditional"]

# How far (in characters) from a primary-term match to look for the
# paired secondary term — wide enough to span a typical single sentence,
# narrow enough that an unrelated mention elsewhere in a long clause can't
# manufacture a false pairing.
_DEFAULT_PROXIMITY_CHARS = 120

# Negation cues that flip a rule pairing from "risky" to "confirmed safe."
# Deliberately excludes "waive(d)" — that word is itself the *positive*
# secondary term for the arbitration_waiver rule, so including it here would
# make that rule permanently self-negate. PHASE_6.5: also excludes
# "excluding" for the same reason — it's the primary-term family for the
# insurance_exclusion rule. "unless"/"except" are deliberately NOT simple
# negation cues (see module docstring "Conditional exceptions") — they live
# in `_EXCEPTION_MARKERS` instead. "neither" and "none" added (P6.6 item 3 —
# "neither party waives" was previously misread as a positive rule hit).
_SIMPLE_NEGATION_CUES = re.compile(r"\b(?:without|no|not|n't|never|neither|none)\b", re.IGNORECASE)
# Markers that introduce a conditional carve-out re-establishing risk despite
# a nearby simple negation — "no X unless Y" / "no X except Y".
_EXCEPTION_MARKERS = re.compile(r"\b(?:unless|except)\b", re.IGNORECASE)
# How far around the matched pairing to look for a simple negation cue.
_NEGATION_WINDOW_BEFORE = 40
_NEGATION_WINDOW_AFTER = 10
# How far *forward* of the matched pairing to look for an exception marker
# that would turn a simple negation into a conditional carve-out. Wider than
# the negation window since the exception clause typically follows the
# negated pairing later in the same sentence ("... applies unless ...").
_EXCEPTION_WINDOW_AFTER = 100


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
    # PHASE_6.6 (docs/PROVISIONAL_DECISIONS.md P6.10): the subcategory's
    # taxonomy-stated upper severity band (Risk_Taxonomy_and_Labeling_Spec.md
    # SS1) — `None` for subcategories whose band already permits HIGH
    # (no cap needed). Applied post-threshold in risk_engine.py; only ever
    # lowers a computed level, never raises one.
    severity_ceiling: RiskLevel | None = None


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
        # PHASE_6.5: broadened primary to cover the general concept of
        # "paying off a loan early," not just "prepay"/"repaid in full" —
        # "early payoff fee," "settles the loan ahead of schedule," and
        # "paid off early" are all common real-world phrasings for the same
        # risk (docs/PROVISIONAL_DECISIONS.md P6.6 item 5b).
        primary=re.compile(
            r"\bprepay\w*\b|\bpre-payment\w*\b|\bpays?\s+off\s+early\b|\brepaid\s+in\s+full\b|"
            r"\bpayoff\b|\bpaid\s+off\b|\bahead\s+of\s+schedule\b|\bsettles?\s+(?:the\s+)?loan\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(r"\bpenalt(?:y|ies)\b|\bcharges?\b|\bfees?\b", re.IGNORECASE),
    ),
    _RuleDefinition(
        rule_id="auto_renewal_notice",
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="auto_renewal",
        # PHASE_6.5: added "renews annually/each year/every year" —
        # automatic-renewal risk isn't limited to clauses using the literal
        # word "automatically"/"auto-" (docs/PROVISIONAL_DECISIONS.md P6.6
        # item 5b). Secondary broadened from bare "notice" to also accept
        # "cancel(s/led/ling/lation)" — the escape-hatch half of this risk
        # pattern is just as often phrased as "unless you cancel" as "unless
        # notice is given"; both name the same mechanism (an action the
        # customer must take to avoid the automatic renewal).
        primary=re.compile(
            r"\bautomatically\s+renew\w*\b|\bauto-renew\w*\b|\brenews?\s+automatically\b|"
            r"\brenews?\s+(?:annually|each\s+year|every\s+year)\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(r"\bnotice\b|\bcancel(?:s|led|ling|lation)?\b", re.IGNORECASE),
        negation_sensitive=False,
        # PHASE_6.6: Risk_Taxonomy_and_Labeling_Spec.md SS1.3 `auto_renewal`
        # default severity is flat "MEDIUM", never MEDIUM-HIGH or HIGH.
        severity_ceiling=RiskLevel.MEDIUM,
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
        # PHASE_6.5: added a generic "terminate this/the agreement"
        # alternative (not requiring the literal word "early") —
        # `secondary` still requires a fee/charge/penalty term nearby, so a
        # plain termination clause with no cost language still can't fire
        # this rule (docs/PROVISIONAL_DECISIONS.md P6.6 item 5b).
        primary=re.compile(
            r"\bearly\s+termination\b|\bterminat\w*\s+(?:this\s+agreement\s+|the\s+agreement\s+)?before\b|"
            r"\bterminat\w*\s+(?:this\s+agreement|the\s+agreement)\b",
            re.IGNORECASE,
        ),
        secondary=re.compile(r"\bfees?\b|\bcharges?\b|\bpenalt(?:y|ies)\b", re.IGNORECASE),
    ),
    # ================================================================
    # PHASE_6.5 additions (docs/PROVISIONAL_DECISIONS.md P6.6 item 5) — 8
    # new rules targeting taxonomy categories with zero prior coverage.
    # Each documented with: taxonomy justification, trigger/secondary terms,
    # negation behavior + reason, and positive/negative/ambiguous examples
    # (ambiguous = ineligible phrasing that correctly does NOT fire this
    # rule, deferring to abstention rather than a false pairing).
    # ================================================================
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md INSURANCE/exclusion. Terms:
        # primary "exclu(de/des/ded/ding/sion/sions)", secondary
        # claim/liability/coverage/loss.
        # Negation: sensitive. "excluding" is deliberately absent from
        # `_SIMPLE_NEGATION_CUES` (P6.9) so this rule's own primary term
        # never self-negates the way "waive" would for arbitration_waiver.
        # Positive: "Claims arising from pre-existing medical conditions are
        #   excluded from coverage under this policy."
        # Negative: "This policy does not exclude coverage for pre-existing
        #   medical conditions."
        # Ambiguous (does not fire — no secondary term nearby): "Exclusions
        #   are listed in Appendix B."
        rule_id="insurance_exclusion",
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="exclusion",
        primary=re.compile(r"\bexclu(?:de|des|ded|ding|sion|sions)\b", re.IGNORECASE),
        secondary=re.compile(r"\bclaim\w*\b|\bliab\w*\b|\bcoverage\b|\bloss(?:es)?\b", re.IGNORECASE),
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md INSURANCE/waiting_period.
        # Negation: sensitive, no self-negation risk term involved.
        # Positive: "A waiting period of 90 days applies before coverage
        #   under this policy becomes effective."
        # Negative: "There is no waiting period before coverage begins under
        #   this policy."
        # Ambiguous (does not fire): "Waiting periods may apply depending on
        #   the type of claim."
        rule_id="insurance_waiting_period",
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="waiting_period",
        primary=re.compile(r"\bwaiting\s+period\b", re.IGNORECASE),
        secondary=re.compile(
            r"\bcoverage\b|\beffective\b|\bapplies\b|\bbegins?\b|\bcommences?\b", re.IGNORECASE
        ),
        # PHASE_6.6: Risk_Taxonomy_and_Labeling_Spec.md SS1.5 `waiting_period`
        # default severity is "LOW-MEDIUM", never HIGH.
        severity_ceiling=RiskLevel.MEDIUM,
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md INSURANCE/deductible.
        # Negation: sensitive.
        # Positive: "A deductible of Rs. 5,000 applies before coverage
        #   begins under this policy."
        # Negative: "This policy has no deductible applicable to covered
        #   claims."
        # Ambiguous (does not fire): "Deductible terms are described in the
        #   policy schedule."
        rule_id="insurance_deductible",
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="deductible",
        primary=re.compile(r"\bdeductible\b", re.IGNORECASE),
        secondary=re.compile(
            r"\bapplies\b|\bapplicable\b|\bpayable\b|\bamount\b|\bcover\w*\b|\bbefore\b", re.IGNORECASE
        ),
        # PHASE_6.6: Risk_Taxonomy_and_Labeling_Spec.md SS1.5 `deductible`
        # default severity is "LOW-MEDIUM", never HIGH.
        severity_ceiling=RiskLevel.MEDIUM,
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md INTEREST_REPAYMENT/rate_change.
        # Negation: sensitive.
        # Positive: "The interest rate shall increase by 2% per annum if the
        #   borrower misses two consecutive installments."
        # Negative: "The interest rate will not change during the term of
        #   this loan."
        # Ambiguous (does not fire): "Interest rate terms are subject to the
        #   bank's policy."
        rule_id="interest_rate_change",
        risk_category=RiskCategory.INTEREST_REPAYMENT,
        risk_subcategory="rate_change",
        # PHASE_6.5 note: "interest rate" is listed first/more specific, but
        # bare "interest" is also accepted — real phrasing often puts a
        # qualifying phrase between "interest" and the rate-change verb
        # ("Interest on the outstanding balance shall increase...") rather
        # than the fixed "interest rate ... increase" collocation. Kept safe
        # from false positives by requiring one of the fairly specific
        # rate-change verbs below as the secondary term, not just any
        # co-occurring word.
        primary=re.compile(r"\binterest\s+rate\b|\brate\s+of\s+interest\b|\binterest\b", re.IGNORECASE),
        secondary=re.compile(
            r"\bincrease\w*\b|\bdecrease\w*\b|\bchanged?\b|\badjust\w*\b|\bvar(?:y|ies|iable)\b|"
            r"\bfloat\w*\b|\brevis\w*\b",
            re.IGNORECASE,
        ),
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md LOSS_OF_RIGHTS/waiver
        # (standalone — not paired with "arbitration" the way
        # arbitration_waiver requires).
        # Negation: sensitive; "waive" itself stays out of the negation cue
        # list (same reasoning as arbitration_waiver) so it can't self-negate.
        # Positive: "The Borrower waives any right to a jury trial in
        #   connection with this agreement."
        # Negative: "No right under this agreement is waived by either
        #   party."
        # Ambiguous (does not fire — no matching secondary term): "Certain
        #   statutory protections may or may not be waived depending on
        #   jurisdiction."
        rule_id="standalone_rights_waiver",
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="waiver",
        primary=re.compile(r"\bwaiv(?:e|es|ed|ing)\b", re.IGNORECASE),
        secondary=re.compile(
            r"\bright\b|\brights\b|\bjury\s+trial\b|\bclaim\b|\bremed(?:y|ies)\b", re.IGNORECASE
        ),
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md DEFAULT/cross_default.
        # Negation: sensitive.
        # Positive: "A default under any other loan or credit agreement
        #   shall constitute a cross-default under this agreement, entitling
        #   the lender to accelerate."
        # Negative: "This loan does not contain a cross-default provision
        #   linked to other agreements."
        # Ambiguous (does not fire): "Cross-default provisions may apply as
        #   set forth elsewhere in this agreement."
        rule_id="cross_default",
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="cross_default",
        primary=re.compile(r"\bcross[- ]default\b", re.IGNORECASE),
        secondary=re.compile(
            r"\bother\s+(?:loan|agreements?|obligations?|indebtedness)\b|\baccelerat\w*\b|\btrigger\w*\b",
            re.IGNORECASE,
        ),
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md RENEWAL/renewal_fee.
        # Negation: sensitive.
        # Positive: "A renewal fee of Rs. 1,500 is payable upon each policy
        #   renewal."
        # Negative: "No renewal fee is charged for this membership."
        # Ambiguous (does not fire): "Renewal fee schedules are published
        #   separately by the insurer."
        rule_id="renewal_fee",
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="renewal_fee",
        primary=re.compile(r"\brenewal\s+fee\b", re.IGNORECASE),
        secondary=re.compile(r"\bpayable\b|\bcharged\b|\bapplies\b|\bdue\b|\bamount\b", re.IGNORECASE),
        # PHASE_6.6: Risk_Taxonomy_and_Labeling_Spec.md SS1.3 `renewal_fee`
        # default severity is flat "MEDIUM", never HIGH.
        severity_ceiling=RiskLevel.MEDIUM,
    ),
    _RuleDefinition(
        # Risk_Taxonomy_and_Labeling_Spec.md TERMINATION/unilateral_termination_right.
        # Negation: sensitive.
        # Positive: "The Lender may terminate this agreement at its sole
        #   discretion at any time without cause."
        # Negative: "Termination of this agreement requires the mutual
        #   written consent of both parties and may not occur unilaterally."
        # Ambiguous (does not fire — no "sole discretion"/"unilateral(ly)"
        #   term): "The agreement may be terminated under certain conditions
        #   at the discretion of the parties."
        rule_id="unilateral_termination",
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="unilateral_termination_right",
        primary=re.compile(r"\bsole\s+discretion\b|\bunilateral(?:ly)?\b", re.IGNORECASE),
        secondary=re.compile(r"\bterminat\w*\b|\bcancel\w*\b|\bend\s+this\s+agreement\b", re.IGNORECASE),
    ),
)


def _has_simple_negation(text: str, window_start: int, window_end: int) -> bool:
    window = text[max(0, window_start) : min(len(text), window_end)]
    return _SIMPLE_NEGATION_CUES.search(window) is not None


def _has_exception_marker(text: str, window_start: int, window_end: int) -> bool:
    window = text[max(0, window_start) : min(len(text), window_end)]
    return _EXCEPTION_MARKERS.search(window) is not None


_SENTENCE_TERMINATOR = re.compile(r"[.;]")


def _sentence_end_after(text: str, position: int) -> int:
    match = _SENTENCE_TERMINATOR.search(text, position)
    return match.start() if match else len(text)


def _resolve_polarity(clause_text: str, span_start: int, span_end: int) -> Polarity:
    """PHASE_6.5 (docs/PROVISIONAL_DECISIONS.md P6.9): a simple-negated
    pairing followed by an exception marker *in the same sentence* is a
    conditional carve-out, not confirmed-safe negation. The forward window
    is capped at the next sentence terminator so an unrelated "unless"/
    "except" in a later, unrelated sentence can't falsely flip an
    unambiguous negative match."""
    negated = _has_simple_negation(
        clause_text, span_start - _NEGATION_WINDOW_BEFORE, span_end + _NEGATION_WINDOW_AFTER
    )
    if not negated:
        return "positive"
    exception_window_end = min(span_end + _EXCEPTION_WINDOW_AFTER, _sentence_end_after(clause_text, span_end))
    if _has_exception_marker(clause_text, span_end, exception_window_end):
        return "conditional"
    return "negative"


# PHASE_6.6 (docs/PROVISIONAL_DECISIONS.md P6.10): built once from `_RULES`
# rather than re-scanned per call — a subcategory maps to at most one rule
# today, so this is a plain dict, not a multi-value structure.
_SUBCATEGORY_SEVERITY_CEILING: dict[str, RiskLevel] = {
    rule.risk_subcategory: rule.severity_ceiling for rule in _RULES if rule.severity_ceiling is not None
}


def subcategory_severity_ceiling(risk_subcategory: str | None) -> RiskLevel | None:
    """The taxonomy-stated upper severity band for a rule-matched subcategory,
    or `None` if that subcategory's band already permits HIGH (no ceiling to
    enforce). `risk_engine.py` applies this as a post-threshold cap — see
    module docstring "Severity ceiling"."""
    if risk_subcategory is None:
        return None
    return _SUBCATEGORY_SEVERITY_CEILING.get(risk_subcategory)


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
            polarity: Polarity = (
                _resolve_polarity(clause_text, span_start, span_end)
                if rule.negation_sensitive
                else "positive"
            )
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    risk_category=rule.risk_category,
                    risk_subcategory=rule.risk_subcategory,
                    polarity=polarity,
                    evidence_text=clause_text[span_start:span_end],
                    start_char=span_start,
                    end_char=span_end,
                )
            )
            break  # one pairing is enough signal for this rule; stop scanning it
    return matches
