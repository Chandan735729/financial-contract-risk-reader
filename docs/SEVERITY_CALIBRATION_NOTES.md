# Severity Calibration Notes (Phase 6.6)

**Status:** living document, not a taxonomy revision. Every claim here traces
to `Risk_Taxonomy_and_Labeling_Spec.md`, `AI_Risk_Engine_Design.md`, or
`PRD_Financial_Contract_Risk_Reader_v2.md` — see `docs/PROVISIONAL_DECISIONS.md`
P6.10 for the corresponding code changes and the smallest-change rationale
behind each one. This document records *reasoning*, not new rules.

## 1. Why this phase exists

Phase 6.5 improved coverage (5 → 13 rules, TEST HIGH recall 0.50 → 1.00) but
at a precision cost (TEST HIGH precision 1.00 → 0.67). Before touching any
threshold, this phase asked: is that drop a benchmark-label problem, a
taxonomy-ambiguity problem, a rule-strength problem, an evidence-strength
problem, an entity/condition-overweighting problem, or an actual engine bug?
The answer, worked out below, is **a mix of the last three** — and none of
them can be fixed by simply moving the HIGH threshold.

## 2. Conceptual separation: detection vs. category vs. severity vs. confidence vs. abstention

Verified against the current implementation (`risk_engine.py`), these are
already five structurally distinct values, computed by different code paths:

| Concept | Field | Computed from |
|---|---|---|
| A. Risk detected | `signals.rule_hit` / `bool(positive_rules)` | `risk_rules.evaluate_rules` |
| B. Risk category | `risk_category` / `risk_subcategory` | `_select_candidate_category` (rule match, or retrieval) |
| C. Severity | `risk_level` | `threshold_to_level(raw_score)`, now capped by `apply_severity_ceiling` |
| D. Confidence | `confidence_level` / `confidence_score` | `calibrated_confidence` — a *separate* weighted function, never derived from `risk_score` |
| E. Abstention | `abstained` / `abstain_reason` | `apply_abstention_rules` — explicit, documented triggers only |

No code path collapses these into one score (`PRD_v2.md` Product Principle
4/9 is honored structurally, confirmed by `test_confidence_score_is_never_a_copy_of_risk_score`
and the new `TestConfidenceIndependence`/`TestSeverityCeiling` cases). The
gap found this phase is not in this separation — it's in what **feeds**
severity (C), covered next.

## 3. Ambiguities and gaps discovered

### 3.1 Documentation inconsistency: does condition completeness drive severity or only confidence?

`Risk_Taxonomy_and_Labeling_Spec.md` §2: *"a fully-specified condition
raises confidence in the assigned severity; an ambiguous one does not raise
severity, it lowers confidence."*

`AI_Risk_Engine_Design.md` §3 (`condition_signal` row): *"a fully specified
chain raises confidence, not severity directly."*

Both documents, in prose, say condition completeness should not be a
severity lever. But `AI_Risk_Engine_Design.md` §4's own formula —
`raw_risk_score = w1*dense + w2*lexical + w3*entity_strength + w4*condition_completeness_score + w5*rule_boost`
— puts it directly into the severity-determining score, and `risk_engine.py`
(`score_clause`) has implemented that formula literally since Phase 5.
**This is a genuine internal inconsistency between two authoritative
documents' own prose and their own formula**, not a coding mistake made
independently of the docs.

**Why it wasn't "fixed" by removing the term this phase:** four
weight-rebalancing hypotheses were tested against the full 30-case DEV
benchmark (script preserved in this phase's development notes; summary in
§4 below). Every one that reduced or removed `weight_condition`'s severity
role broke multiple currently-*correct* DEV cases — including the
taxonomy's own canonical worked example (`Risk_Taxonomy_and_Labeling_Spec.md`
§4's positive example, reproduced as the `prepayment_penalty_with_percentage`
DEV case). The DEV benchmark's gold labels were themselves calibrated
(Phase 5) against a formula that includes this term, so the inconsistency
is now load-bearing in the one place we're not allowed to change without
real justification (DEV). **Conclusion: this needs a genuine `taxonomy_v2`
resolution backed by real inter-annotator-labeled data (`Risk_Taxonomy_and_Labeling_Spec.md`
§7's own versioning rule for changing severity semantics), not a
code-only fix from one engineer's judgment call.** Reported, not
silently resolved, per this phase's own instructions.

### 3.2 Missing per-subcategory severity ceiling (real bug, fixed this phase)

The taxonomy (`Risk_Taxonomy_and_Labeling_Spec.md` §1) gives every
subcategory a *default severity band* — some are flat MEDIUM
(`auto_renewal`, `renewal_fee`), some LOW–MEDIUM (`waiting_period`,
`deductible`), some flat HIGH (`acceleration`, `cross_default`), some
MEDIUM–HIGH. The scoring formula, before this phase, had **no notion of
which subcategory it was scoring** — the identical rule/entity/condition
combination formula applied uniformly regardless of subcategory. Empirically
confirmed reachable (not hypothetical): a fee-and-surcharge-heavy
`auto_renewal_notice` match scored 0.83/**HIGH**, despite `auto_renewal`'s
taxonomy band never exceeding MEDIUM.

**Fixed this phase:** `risk_rules._RuleDefinition.severity_ceiling` +
`risk_engine.apply_severity_ceiling` — a post-threshold cap, applied per the
rule-matched subcategory, that can only ever *lower* a computed level, never
raise one. See `docs/PROVISIONAL_DECISIONS.md` P6.10 for why this is safe
(monotonic; verified against all 30 DEV + 12 TEST + 10 adversarial cases
with zero regressions, since no currently-*correct* case was being
incorrectly elevated for a ceiling-bearing subcategory). Applied to 4 of the
13 rules: `auto_renewal_notice`, `insurance_waiting_period`,
`insurance_deductible`, `renewal_fee` — all their taxonomy bands top out at
MEDIUM.

**Deliberately not built this phase:** a severity *floor* (e.g. guaranteeing
`cross_default`'s flat-HIGH band always shows at least MEDIUM even under
weak signal). A false floor-elevation is a much higher-risk mistake than a
missing ceiling (it directly risks manufacturing a HIGH/MEDIUM claim without
real evidence, which `Grounding_and_Evidence_Spec.md` and Product Principle
5 explicitly forbid) — a floor mechanism needs its own careful design pass,
not a same-phase bolt-on.

### 3.3 Entity magnitude has no category norms

`AI_Risk_Engine_Design.md` §4 Step 1's own pseudocode comment:
`entity_strength: f(entity count, entity magnitude vs. category norms)`.
The actual implementation (`risk_engine.score_entities`) has **no
category-norm awareness at all** — a flat `+0.10` magnitude bonus applies to
any percentage/rate entity `>= 1.0`, regardless of whether `5%` is a large
prepayment penalty or a modest interest-rate adjustment. This is another
documented-intent-vs-implementation gap. **Not fixed this phase** — doing so
correctly requires actual category-specific magnitude norms (e.g. "a
prepayment penalty above 3% is unusually high; a deductible above ₹10,000
is unusually high"), which is domain/data work, not something to invent
from first principles in one engineering pass. Recorded here as a concrete,
scoped recommendation for the next data-collection phase.

## 4. Weight-rebalancing hypotheses tested and rejected

All tested by re-scoring the full 30-case DEV benchmark with `dataclasses.replace`
variants of `RiskEngineConfig`, never touching TEST:

| Hypothesis | DEV mismatches | Why rejected |
|---|---|---|
| `weight_condition=0.05, weight_entity=0.25` | 8 | Breaks 3 rule-only-MEDIUM DEV cases (drop to UNKNOWN) and 2 HIGH DEV cases (drop to MEDIUM) |
| `weight_condition=0, weight_entity=0.25, weight_corroboration=0.25` | 10 | Same failures plus 2 new false elevations (MEDIUM→HIGH) |
| `weight_condition=0, weight_entity=0.30` | 9 | Same rule-only-MEDIUM breakage; doesn't fully compensate HIGH cases either |
| `weight_condition=0, weight_rule=0.40` | 9 | Same breakage pattern; a flat rule-weight increase also risks pushing weak/coincidental rule matches toward MEDIUM everywhere |
| Gate condition term off when corroboration already fired | 5 | Fixes the disputed `interest_rate_change` case specifically, but breaks 5 *other* DEV HIGH cases with the identical rule+entity+condition signal shape (no way to distinguish them mechanically) |

**Conclusion:** the disputed TEST cases (`interest_rate_change`,
`deductible`) and multiple correct DEV HIGH cases currently share the exact
same signal shape (rule + entity + full condition chain). There is no
DEV-safe way to separate "this one should be MEDIUM" from "this one should
be HIGH" using only the signals the engine currently has access to. Per
§3.1's taxonomy band analysis, this isn't even necessarily a bug — both
outputs are *within* the taxonomy's own stated band for these subcategories.
No engine weight was changed as a result.

## 5. Severity matrix

Bands below are taxonomy defaults (`Risk_Taxonomy_and_Labeling_Spec.md`
§1), not new inventions. "Engine reaches" describes verified current
behavior for the given example (not a promise for all phrasings). Examples
are calibration references, not literal production rules — see
`backend/tests/fixtures/risk_engine_benchmark.py` for the actual DEV
fixtures.

### FINANCIAL_COST — `prepayment_penalty` (HIGH-leaning, rule-covered)
- **LOW:** "Borrower may prepay at any time without penalty." → confirmed-negative rule match → LOW.
- **MEDIUM:** "A prepayment fee may apply." → no extractable entity, vague trigger → engine currently abstains to UNKNOWN (no rule secondary-term match on bare "fee" without a percentage/amount nearby to anchor it) — see §6.1.
- **HIGH:** "Borrower shall pay a prepayment penalty equal to 5% ... if the loan is repaid within 24 months." → rule + entity magnitude + full condition → HIGH (0.74–0.77 depending on additional entities).
- **UNKNOWN:** "Prepayment provisions may apply under certain circumstances." → no rule pairing, no entity, no condition marker → UNKNOWN (correct: genuinely vague).

### FINANCIAL_COST — `late_payment_fee`, `processing_fee`, `hidden_charge`, `interest_adjustment`, `renewal_price_increase`, `other_monetary_penalty`
**No dedicated rule exists for any of these five subcategories.** Reported
here explicitly rather than left implicit — a clause squarely matching one
of these currently depends entirely on `missed_payment_acceleration` (for
late-payment-adjacent phrasing) or falls to UNKNOWN. Genuine, uncovered gap.

### DEFAULT — `acceleration` (flat HIGH, rule-covered), `cross_default` (flat HIGH, rule-covered)
- **HIGH:** "If the borrower fails to pay ..., the lender may accelerate the entire outstanding balance." → rule + condition (+ entity if amount present) → HIGH.
- **MEDIUM:** "In case of late payment, acceleration ... shall apply immediately." (no entity) → rule + full condition, no entity → MEDIUM (0.45) — see §6.1 on whether a flat-HIGH category should ever cap this low.
- **UNKNOWN:** no rule pairing, no entity, no condition → UNKNOWN.
- `missed_payment`, `default_trigger`, `foreclosure`, `collateral_enforcement`: **no dedicated rule.** Reported as coverage gaps.

### RENEWAL — `auto_renewal` (flat MEDIUM, rule-covered, **now ceiling-capped**), `renewal_fee` (flat MEDIUM, rule-covered, **now ceiling-capped**)
- **LOW:** "This membership does not renew automatically; it lapses ... unless the member actively opts to renew." → confirmed-negative → LOW.
- **MEDIUM:** "Unless the policyholder provides notice, this policy renews automatically." → rule fires, capped at MEDIUM regardless of any additional entity/condition strength (§3.2 fix).
- **HIGH:** **never** — taxonomy band tops out at MEDIUM; the engine now structurally cannot output HIGH for this subcategory (`apply_severity_ceiling`).
- **UNKNOWN:** no automatic-renewal marker at all in the text.
- `renewal_notice_period`, `cancellation_restriction`: **no dedicated rule.**

### LOSS_OF_RIGHTS — `arbitration` (MEDIUM–HIGH, rule-covered), `waiver` (MEDIUM–HIGH, rule-covered, standalone)
- **LOW:** "This agreement does not require arbitration and no right is waived." → confirmed-negative → LOW.
- **MEDIUM:** "If a dispute arises ..., it shall be resolved through ... arbitration, and the parties waive the right to a jury trial." (no entity, rule+condition only) → MEDIUM.
- **HIGH:** not currently reached by any DEV/TEST example for this subcategory (arbitration/waiver clauses rarely carry a financial entity) — plausible only with an unusually strong condition+entity combination; no example currently exercises it.
- **UNKNOWN:** "The parties agree that any claim shall be settled by binding arbitration, thereby waiving the right to sue in court." (rule fires, no entity, no condition marker at all — an *unconditional* clause) → currently UNKNOWN. See §6.1 — this is the single most-discussed open question in this document.
- `limitation_of_remedies`, `class_action_waiver` (standalone, without the word "waiv..." itself present — e.g. "the customer may not join a class action"), `dispute_restriction`: **no dedicated rule** beyond the generic `standalone_rights_waiver` pairing.

### INSURANCE — `exclusion` (MEDIUM–HIGH, rule-covered), `waiting_period` (LOW–MEDIUM, rule-covered, **now ceiling-capped**), `deductible` (LOW–MEDIUM, rule-covered, **now ceiling-capped**)
- **LOW:** "This policy does not exclude coverage for pre-existing medical conditions." / "There is no waiting period ..." / "This policy has no deductible ..." → confirmed-negative → LOW.
- **MEDIUM:** "A waiting period of 90 days applies before coverage ... becomes effective." / "A deductible of Rs. 5,000 applies before coverage begins." → rule + entity, capped at MEDIUM.
- **HIGH:** possible for `exclusion` only (MEDIUM–HIGH band; not ceiling-capped) with a strong entity+condition combination — no current DEV/TEST example reaches it.
- **UNKNOWN:** "The insurer shall not be liable for any claim ..." (exclusion concept, but the specific wording doesn't match the rule's `exclu...` term family — see §6.2) → currently UNKNOWN, a genuine extraction gap, not a severity question.
- `coverage_limitation`, `claim_condition`: **no dedicated rule.**

### INTEREST_REPAYMENT — `rate_change` (MEDIUM–HIGH, rule-covered)
- **LOW:** "The interest rate ... is fixed for the entire tenure and will not change ..." → confirmed-negative → LOW.
- **MEDIUM or HIGH — genuinely ambiguous within band:** "The interest rate shall increase by 2.5% per annum if the borrower misses two consecutive installments." → rule + entity + full condition → engine reaches HIGH; **both MEDIUM and HIGH are within the taxonomy's stated band** (§3.1/§4). This is the disputed TEST case's exact shape.
- **UNKNOWN:** "Interest rate terms are subject to the bank's policy." → no rate-change verb nearby → UNKNOWN.
- `variable_interest`, `compounding`, `repayment_condition`, `payment_schedule` (LOW-banded structural terms): **no dedicated rule** — `payment_schedule` in particular should very rarely if ever reach MEDIUM/HIGH once a rule exists for it; noted for any future rule addition.

### TERMINATION — `early_termination_fee` (MEDIUM–HIGH, rule-covered), `unilateral_termination_right` (MEDIUM–HIGH, rule-covered)
- **LOW:** "Either party may terminate this agreement ... without cause and without penalty." → confirmed-negative → LOW.
- **MEDIUM:** "The company may terminate this agreement at its sole discretion ... upon 15 days written notice." → rule + condition, no entity → MEDIUM.
- **HIGH:** "An early termination fee of Rs. 5,000 applies if the agreement is terminated before the end of the term." → rule + entity + full condition → HIGH.
- **UNKNOWN:** no termination-related rule pairing at all.
- `termination_restriction`: **no dedicated rule.**

## 6. Unresolved questions (recommended for a future phase with real labeled data)

### 6.1 Should an explicit, unconditional rule match ever abstain to UNKNOWN?

`test_arbitration_no_condition_marker` and `test_standalone_jury_waiver_no_rule_coverage`
both: fire a positive, unambiguous rule match on explicit text ("waives any
right to a jury trial") with no financial entity and no conditional
connective (because the clause is *mandatory*, not conditional — there is
nothing to extract). Current behavior: `raw_score = weight_rule` alone
(0.35) lands in the LOW band, and `apply_abstention_rules` requires
*positive* evidence for LOW (a negative-polarity match), which a positive
rule hit isn't — so it abstains to UNKNOWN.

Arguments this is correct: UNKNOWN protects against overclaiming when the
formula's other signals (entity, condition, retrieval) are silent — exactly
Product Principle 3's "no match ≠ safe," generalized to "one weak match ≠
confident."

Arguments this is too conservative: `PRD_v2.md` §9 states UNKNOWN should
correlate with *genuine ambiguity*, not be "a dumping ground." These two
example clauses are not linguistically ambiguous at all — they are complete,
explicit statements. The taxonomy bands both subcategories MEDIUM–HIGH.
Abstaining here conflates "the clause is unclear" with "our multi-signal
formula happens to have only one active signal for this particular
subcategory shape (no entity to extract)."

**Why not fixed this phase:** any fix that grants extra severity credit to
a bare positive rule match risks the opposite failure — false MEDIUM/HIGH
on a rule that fired coincidentally over less-explicit or boilerplate text.
Distinguishing "complete, explicit, unconditional clause" from "weak/
coincidental match" is a real feature (perhaps: sentence-completeness
detection, or a per-rule "this pattern is reliable enough to stand alone"
flag validated against real data) that this phase's instructions
specifically warn against inventing speculatively. Recommended next step:
collect real-world unconditional-clause examples and measure whether
rule-only-positive matches are trustworthy enough, on their own, to justify
a documented, narrow exception.

### 6.2 `insurance_exclusion` misses "shall not be liable" phrasing

Genuine extraction gap, not a severity question — see `risk_test_holdout.py`'s
`test_insurance_exclusion_no_rule_coverage` notes. Broadening the rule's
primary pattern to catch "not liable" phrasing was evaluated and rejected
in Phase 6.5 due to self-negation risk (the same class of trap
`excluding`/`waive` were kept out of the negation-cue list for). Left open.

### 6.3 Entity magnitude category norms (§3.3) and a severity floor (§3.2) remain unimplemented, as scoped above.
