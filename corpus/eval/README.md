# Evaluation Framework (Phase 6)

This directory turns evaluation into a permanent engineering gate:
reproducible metrics, calibration, error analysis, and regression
detection for every stage of the pipeline (parsing through risk
classification). It answers three questions on every run: **how accurate is
the system, where does it fail, and can we detect regressions?**

## What this is not

**Every number produced anywhere in this directory is measured against
synthetic, hand-authored benchmark data.** `Dataset_and_Evaluation_Spec.md`
§4 requires a real-world benchmark — independently annotated real
documents, messy/scanned sources, inter-annotator agreement checking —
which **does not exist yet**. Corpus collection itself
(`Dataset_and_Evaluation_Spec.md` §1) was out of scope through Phase 5;
`corpus_patterns` is empty in this repository today. Do not cite any number
from this directory as production accuracy. Every `run_*.py` script prints
this caveat in its own output as well, so it travels with the numbers.

## Running the evaluation suite

All commands run from `backend/` (so `app`/`tests` are importable) or with
the repo root prepended to `PYTHONPATH`:

```bash
cd backend
python ../corpus/eval/run_all.py            # master regression gate (fast; no embedding model needed)
python ../corpus/eval/run_segmentation_eval.py
python ../corpus/eval/run_retrieval_eval.py  # loads the embedding model — slower
python ../corpus/eval/run_entity_eval.py
python ../corpus/eval/run_condition_eval.py
python ../corpus/eval/run_evidence_eval.py
python ../corpus/eval/run_generation_eval.py
python ../corpus/eval/run_risk_engine_eval.py
python ../corpus/eval/run_abstention_eval.py
python ../corpus/eval/run_calibration_eval.py
python ../corpus/eval/run_ablation.py
python ../corpus/eval/run_threshold_tuning.py
```

`run_all.py` is the one to run after every pipeline-affecting change. It
covers segmentation, entity, condition, evidence, generation/grounding
guard, risk classification (DEV + TEST + adversarial), abstention, and
calibration; it deliberately
excludes retrieval/ablation/threshold-tuning (slower setup — an embedding
model and, for retrieval, an in-memory Chroma collection) so it stays fast
enough to run routinely. It exits non-zero on a **hard gate** failure (see
below) and always writes a new, timestamped, versioned JSON report to
`corpus/eval/results/` (gitignored — regenerable, not a source-of-truth
artifact).

## Dataset organization

```
corpus/eval/
  schema.py              # ClauseGroundTruth — the one canonical ground-truth record
  versioning.py           # run metadata (git commit, taxonomy/corpus/engine/embedding/benchmark versions)
  datasets/
    entity_ground_truth.py         # DEV + TEST
    condition_ground_truth.py      # DEV + TEST
    evidence_ground_truth.py       # DEV + TEST, plus integrity probes
    generation_ground_truth.py     # DEV + TEST + adversarial, scripted LLM outputs (no live calls)
    abstention_ground_truth.py     # ambiguous vs. clear-boundary cases
    adversarial_risk_cases.py      # Phase 6 spec cases A-I + one supplementary gap
    risk_test_holdout.py           # held-out risk-classification TEST split
    retrieval_terminology_drift.py # supplementary retrieval stress queries
  metrics/                # pure metric functions (no I/O) — entity, condition,
                           # evidence, calibration, abstention, ablation
  reports/
    error_analysis.py     # Dataset_and_Evaluation_Spec.md SS7's 14 error categories
  run_*.py                # one runnable script per evaluation area
  run_all.py              # master regression gate
  results/                # timestamped run outputs (gitignored)
```

Segmentation (`backend/tests/fixtures/segmentation_benchmark.py`) and the
core risk-classification DEV set
(`backend/tests/fixtures/risk_engine_benchmark.py`) are Phase 3/5 fixtures
left in place rather than duplicated here — `corpus/eval/`'s scripts import
them directly.

### Split rules (non-negotiable)

- **DEV**: used for threshold/weight tuning (`run_threshold_tuning.py`) and
  ablation analysis (`run_ablation.py`). `risk_engine_v1`'s weights (Phase
  5) were chosen against this split.
- **TEST**: held out, reported only, **never** used to select a weight or
  threshold. Small (12 risk cases, 3 entity, 2 condition) — a floor on
  statistical power, stated explicitly rather than glossed over. See
  `risk_test_holdout.py`'s docstring for an important honesty caveat: this
  is a process-separation exercise, not a genuinely blind held-out set,
  since the same person tuned the engine and wrote these cases.
- **ADVERSARIAL**: stress cases (Phase 6 spec §9's cases A–I). Never used
  for tuning either. Several of the spec's own case descriptions are
  hedged ("possibly," "likely," "test carefully") — preserved as
  `expected_levels`/`forbidden_levels`/`strict` rather than forced into one
  gold answer.
- Calibration is **fit on DEV only, evaluated on both DEV and TEST**
  (`run_calibration_eval.py` never calls `fit_isotonic_calibration` with
  TEST-split samples).

## What Phase 6 actually found

This is the part worth reading before the numbers. Running this framework
surfaced real, load-bearing gaps — not edge cases invented to look
thorough:

1. **The reference corpus is empty.** With no `corpus_patterns` rows, dense
   and lexical retrieval contribute exactly zero signal for every clause in
   production today. Every positive detection currently depends entirely on
   the five narrow deterministic rules in `risk_rules.py`.
2. **Those five rules cover a small slice of the taxonomy and are
   phrasing-literal.** Whole categories (every `insurance` subcategory,
   `interest_repayment/rate_change`, standalone rights waivers) have zero
   rule coverage. On the held-out TEST split, HIGH-risk **precision stayed
   at 1.00** (no false alarms) but HIGH-risk **recall dropped to 0.50** —
   the system is conservative, not wrong, when it encounters unfamiliar
   phrasing.
3. **The condition extractor doesn't handle "consequence-before-trigger"
   phrasing** ("Borrower shall pay X if Y" — the natural English order for
   many contract sentences), which is why adversarial Case A (the spec's
   own canonical HIGH example) currently scores MEDIUM. It also doesn't
   recognize "provided that," "subject to," or "notwithstanding" as trigger
   markers at all.
4. **The rule layer's negation handling doesn't understand nested
   conditional exceptions** — "no penalty applies *unless* X" reads as a
   flat negation (safe) rather than "X re-establishes the penalty"
   (adversarial Case C), and "neither party waives" isn't recognized as
   negated at all (missing "neither" from the negation-cue list).
5. **Isotonic calibration fit on the 15-case DEV split made ECE *worse* on
   TEST** (0.12 → 0.46) — direct, measured evidence that the current sample
   size is too small to fit a calibration mapping that generalizes, exactly
   the failure mode `Dataset_and_Evaluation_Spec.md` §6 and this phase's
   "never calibrate on TEST" rule exist to guard against.

None of these were patched in Phase 6 — this phase is evaluation
infrastructure, not an engine-change phase (see the phase brief). They're
recorded as `known_gap=True` cases and in `reports/error_analysis.py`'s
`KNOWN_FINDINGS`, so `run_all.py` has a real, honest baseline for future
regression comparisons instead of a benchmark quietly rigged to pass.

## What Phase 6.5 did (and honestly didn't) fix

Phase 6.5 (docs/PROVISIONAL_DECISIONS.md P6.6/P6.8/P6.9) addressed items
1–4 above through general fixes, not TEST-string patches — see
`corpus/eval/reports/error_analysis.py`'s module docstring for the exact
list of what changed. **Before → after** (DEV n=15→29, TEST n=12 unchanged):

| Metric | Before | After |
|---|---|---|
| DEV macro F1 | 1.00 (n=15) | 1.00 (n=29, expanded benchmark) |
| TEST macro F1 | 0.40 | 0.54 |
| TEST HIGH precision | 1.00 | 0.67 |
| TEST HIGH recall | 0.50 | 1.00 |
| Entity extraction F1 | 1.00 | 1.00 (unchanged) |
| Evidence precision | 1.00 | 1.00 (unchanged); fabrication_leak_count 0 both |
| Abstention UNKNOWN precision | 1.00 | 1.00 (unchanged) |
| DEV / TEST calibration ECE | 0.57 / 0.12 | 0.53 / 0.14 (still not statistically meaningful at this sample size) |
| Adversarial (A–I + supplementary) | 7 pass, 2 known_gap, 1 observe | 9 pass, 0 known_gap, 1 observe (Case E, no fixed expected label) |
| Reference corpus | empty | 26 `source="synthetic_seed"` patterns, 13/~35 subcategories |
| Rule count | 5 | 13 |

(Entity F1 and evidence precision dipped transiently to 0.96/0.75 mid-implementation —
two DEV/TEST ground-truth entries were stale relative to the new, correct
extractor behavior (a mislabeled word-form-percent case, and two evidence
cases missing a newly-and-correctly-found consequence span after the
consequence-before-trigger fix). Both were corrected to the actual verified
extractor output, and a real bug the investigation surfaced — "Rs." being
misread as a sentence boundary — was fixed with a regression test. Reported
here rather than silently smoothed over.)

**Read the TEST HIGH precision drop honestly, not defensively:** it comes
from exactly one case (`test_interest_rate_change_no_rule_coverage`) where
the new `interest_rate_change` rule now fires — closing the original
"no coverage" gap — but the resulting score lands on HIGH where this file's
gold label says MEDIUM. That was *not* weight-tuned away, because the only
justification for such a tuning would be this single TEST case (see that
case's `notes` in `risk_test_holdout.py`). Two more cases
(`test_deductible_no_rule_coverage`, and the newly-covered-but-still-abstained
`test_standalone_jury_waiver_no_rule_coverage`) show the same pattern: real
coverage improvement, imperfect exact match against a small, hand-guessed
gold set. Item 5 (calibration DEV→TEST transfer) was out of scope for Phase
6.5 and remains unfixed — still uncalibrated, still `apply_calibration` is
the identity function.

## Metrics reference

| Area | Script | Key metrics |
|---|---|---|
| Segmentation | `run_segmentation_eval.py` | boundary P/R/F1, text coverage, empty/duplicate/tiny/huge-clause rates |
| Retrieval | `run_retrieval_eval.py` | Recall@1/3/5, MRR — separately for dense-only, lexical-only, and the hybrid union, plus doc-type/positive-negative/paraphrase/terminology-drift breakdowns |
| Entities | `run_entity_eval.py` | P/R/F1 overall and per type, value/span correctness, false-positive rate |
| Conditions | `run_condition_eval.py` | per-field exact-match accuracy, chain-completeness accuracy |
| Evidence | `run_evidence_eval.py` | evidence P/R/F1, citation correctness, fabrication-leak count (must be 0) |
| Generation / Grounding Guard | `run_generation_eval.py` | grounded explanation rate, fallback rate, unsupported claim rate, citation correctness, generation failure rate, unsupported-claim-leak count (must be 0) |
| Risk classification | `run_risk_engine_eval.py` | P/R/F1 per level, macro F1, HIGH precision/recall, FP/FN rate, DEV vs. TEST vs. adversarial |
| Abstention | `run_abstention_eval.py` | UNKNOWN precision/recall, false-abstention rate, ambiguity-capture rate |
| Calibration | `run_calibration_eval.py` | reliability bins, ECE (overall/by level), isotonic fit, DEV→TEST transfer, risk×confidence cross-tab |
| Ablation | `run_ablation.py` | macro F1 / HIGH P-R per signal combination |
| Threshold tuning | `run_threshold_tuning.py` | lexicographic ranking of candidate thresholds on DEV only |

## Hard gates vs. provisional warnings

`run_all.py` distinguishes two kinds of finding:

- **Hard gates** (fail the run, exit code 1): zero fabrication leaks in the
  evidence-integrity probes; every HIGH/MEDIUM result carries verified
  evidence; the DEV split doesn't regress below its established macro F1
  floor; zero unsupported-claim leaks in the generation/grounding guard
  evaluation; every simulated LLM-call-failure probe correctly falls back to
  the safe state; no unhandled exception. These hold regardless of benchmark
  size — they're safety/regression invariants, not accuracy claims.
- **Provisional warnings** (printed, non-gating): TEST-split accuracy,
  calibration ECE, segmentation/retrieval numbers. Phase 6 spec: *"If
  thresholds are not yet scientifically justified: mark them as provisional
  and use them only as development warnings."* The current sample sizes
  (29 DEV, 12 TEST cases as of Phase 6.5) do not justify a hard numeric accuracy bar.

## Interpreting a "PASSED" gate

A passing `run_all.py` run means **no safety-critical regression was
detected on this synthetic benchmark**. It does not mean the system is
production-accurate — TEST-split HIGH precision/recall (0.67/1.00 as of
Phase 6.5, see "What Phase 6.5 did" above) are, by design, not gated, and
reported every run so they stay visible instead of disappearing into a
"gate passed" green checkmark.

## Limitations (stated explicitly, per Phase 6 spec)

- No real-world benchmark exists. `Dataset_and_Evaluation_Spec.md` §4
  (independently annotated real documents, inter-annotator agreement) is
  still open work.
- Sample sizes are small (29 DEV, 12 TEST cases as of Phase 6.5). Precision/
  recall/F1/ECE numbers at this scale are directional, not statistically
  robust — do not treat a 100% or 0% on a 3-case subgroup as a strong
  claim.
- The TEST split is not a genuinely blind evaluation (see `risk_test_holdout.py`).
- Calibration is explicitly uncalibrated (`docs/PROVISIONAL_DECISIONS.md`
  P5.2) — this framework measures the gap, it does not close it.
