"""Signal-ablation runner tests — Phase 6 spec SS14, SS19.

Structural correctness of `corpus/eval/metrics/ablation.py`: every declared
variant runs without crashing, `full_engine` uses the real default weights,
and single-signal variants use genuinely zeroed weights (not accidentally
the full config).
"""

from __future__ import annotations

from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG
from corpus.eval.metrics.ablation import build_ablation_variants, run_ablation
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES


class TestBuildAblationVariants:
    def test_nine_variants_declared(self):
        variants = build_ablation_variants()
        names = {v.name for v in variants}
        assert names == {
            "dense_only",
            "lexical_only",
            "entity_only",
            "condition_only",
            "rule_only",
            "dense_plus_lexical",
            "retrieval_plus_entities",
            "retrieval_plus_entities_plus_conditions",
            "full_engine",
        }

    def test_full_engine_variant_matches_default_config(self):
        variants = build_ablation_variants()
        full = next(v for v in variants if v.name == "full_engine")
        assert full.config == DEFAULT_RISK_ENGINE_CONFIG

    def test_dense_only_variant_zeroes_every_other_weight(self):
        variants = build_ablation_variants()
        dense_only = next(v for v in variants if v.name == "dense_only")
        assert dense_only.config.weight_dense == DEFAULT_RISK_ENGINE_CONFIG.weight_dense
        assert dense_only.config.weight_lexical == 0.0
        assert dense_only.config.weight_entity == 0.0
        assert dense_only.config.weight_condition == 0.0
        assert dense_only.config.weight_rule == 0.0
        assert dense_only.config.weight_corroboration == 0.0

    def test_retrieval_plus_entities_keeps_exactly_three_weights(self):
        variants = build_ablation_variants()
        variant = next(v for v in variants if v.name == "retrieval_plus_entities")
        assert variant.config.weight_dense == DEFAULT_RISK_ENGINE_CONFIG.weight_dense
        assert variant.config.weight_lexical == DEFAULT_RISK_ENGINE_CONFIG.weight_lexical
        assert variant.config.weight_entity == DEFAULT_RISK_ENGINE_CONFIG.weight_entity
        assert variant.config.weight_condition == 0.0
        assert variant.config.weight_rule == 0.0


class TestRunAblation:
    def test_runs_every_variant_without_crashing(self):
        results = run_ablation(list(BENCHMARK_CASES))
        assert len(results) == 9

    def test_full_engine_scores_at_least_as_well_as_every_ablated_variant(self):
        results = run_ablation(list(BENCHMARK_CASES))
        full = next(r for r in results if r.variant_name == "full_engine")
        for r in results:
            if r.variant_name != "full_engine":
                assert r.macro_f1 <= full.macro_f1

    def test_results_are_reproducible_deterministic(self):
        results_a = run_ablation(list(BENCHMARK_CASES))
        results_b = run_ablation(list(BENCHMARK_CASES))
        assert [r.macro_f1 for r in results_a] == [r.macro_f1 for r in results_b]
