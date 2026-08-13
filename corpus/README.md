# corpus/

Holds the labeled reference pattern corpus (`Dataset_and_Evaluation_Spec.md`)
and the evaluation harness (`corpus/eval/` — see `corpus/eval/README.md`)
that the Retrieval Service and Risk Engine depend on.

**PHASE_6.5 update (docs/PROVISIONAL_DECISIONS.md P6.8):** the
`corpus_patterns` table is no longer empty, but it is **not** the
production-quality real-world corpus `Dataset_and_Evaluation_Spec.md` SS1
calls for (a CUAD subset + permissioned, provenance-tracked scraping of
Indian loan/insurance T&Cs) — that sourcing work remains scoped but
unexecuted. `corpus/build/` seeds a small, honestly-labeled corpus
(`source="synthetic_seed"`, 26 hand-authored patterns covering the 13
taxonomy subcategories with a deterministic rule) so the retrieval pipeline
has something real to index and query end-to-end. Run
`python ../corpus/build/build_corpus.py` from `backend/` to (re)build it —
idempotent, only ever touches `synthetic_seed` rows.

**Do not read `source="synthetic_seed"` coverage as real-world corpus
coverage.** It exercises the pipeline (DB upsert, embedding, Chroma
indexing, dense+lexical retrieval, version isolation) mechanically; it does
not validate retrieval quality against real, messy contract language. See
`corpus/build/seed_patterns.py`'s docstring for the full provenance
statement and the coverage table below.

The evaluation harness (`corpus/eval/`) is built out as of Phase 6 and does
not wait on the corpus — see `corpus/eval/README.md` for how to run it, its
DEV/TEST/ADVERSARIAL split rules, and its explicit limitations.

Never commit real user-uploaded documents here. `corpus/build/` holds only
synthetic, hand-authored seed patterns (`source="synthetic_seed"`);
`corpus/eval/` holds only synthetic, hand-authored evaluation fixtures. A
real, provenance-tracked reference corpus (`source` values like `"cuad"` /
`"scraped_indian"`, per `Risk_Taxonomy_and_Labeling_Spec.md` SS6) is still
open future work — see `Dataset_and_Evaluation_Spec.md` SS1.

## Corpus coverage (as of Phase 6.5)

13 of ~35 taxonomy subcategories have both a deterministic rule
(`backend/app/services/risk_rules.py`) and a seed pattern pair (positive +
negative): `prepayment_penalty`, `auto_renewal`, `arbitration`,
`acceleration`, `early_termination_fee`, `insurance/exclusion`,
`insurance/waiting_period`, `insurance/deductible`, `interest_repayment/rate_change`,
`loss_of_rights/waiver` (standalone), `cross_default`, `renewal_fee`,
`unilateral_termination_right`. Every other taxonomy subcategory
(`Risk_Taxonomy_and_Labeling_Spec.md` SS1) — including
`coverage_limitation`, `claim_condition`, `compounding`,
`class_action_waiver`, `cancellation_restriction`, `foreclosure`,
`collateral_enforcement` — has neither a rule nor a seed pattern and is a
genuine, reported gap, not a silent omission.
