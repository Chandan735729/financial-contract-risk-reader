"""Structural validation for the PHASE_6.5 synthetic seed corpus —
docs/PROVISIONAL_DECISIONS.md P6.8.

Pure data-shape checks only — no DB, no embedding model (those are
exercised manually via `corpus/build/build_corpus.py`, matching the existing
convention that `run_retrieval_eval.py`/`run_ablation.py` are excluded from
the fast `pytest`/`run_all.py` gate for the same reason).
"""

from __future__ import annotations

from corpus.build.seed_patterns import SEED_PATTERNS, SOURCE_SYNTHETIC_SEED


class TestSeedPatternProvenance:
    def test_every_pattern_tagged_synthetic_seed(self):
        assert all(p.source == SOURCE_SYNTHETIC_SEED for p in SEED_PATTERNS)

    def test_source_is_never_a_real_world_value(self):
        # Guards against ever accidentally tagging a seed row as if it came
        # from real sourcing (P6.8: never conflate synthetic and real
        # corpus provenance).
        assert not any(p.source in ("cuad", "scraped_indian") for p in SEED_PATTERNS)


class TestSeedPatternCoverage:
    def test_every_pattern_has_positive_and_negative_counterpart(self):
        by_subcategory: dict[str, set[bool]] = {}
        for p in SEED_PATTERNS:
            by_subcategory.setdefault(p.risk_subcategory, set()).add(p.is_negative_example)
        for subcategory, polarities in by_subcategory.items():
            assert polarities == {True, False}, f"{subcategory} missing a positive or negative example"

    def test_no_duplicate_pattern_text(self):
        texts = [p.pattern_text for p in SEED_PATTERNS]
        assert len(texts) == len(set(texts))

    def test_no_pattern_copied_from_eval_fixtures(self):
        # P6.8: the seed corpus must not be inflated by copying eval
        # fixture text into it — that would make retrieval "succeed" only
        # by finding its own test data.
        from corpus.eval.datasets.adversarial_risk_cases import ADVERSARIAL_CASES
        from corpus.eval.datasets.risk_test_holdout import RISK_TEST_HOLDOUT

        eval_texts = {c.text for c in ADVERSARIAL_CASES} | {c.text for c in RISK_TEST_HOLDOUT}
        seed_texts = {p.pattern_text for p in SEED_PATTERNS}
        assert eval_texts.isdisjoint(seed_texts)


class TestSeedPatternSchema:
    def test_all_confidences_in_range(self):
        assert all(0.0 <= p.annotator_confidence <= 1.0 for p in SEED_PATTERNS)

    def test_all_pattern_text_non_empty(self):
        assert all(p.pattern_text.strip() for p in SEED_PATTERNS)
