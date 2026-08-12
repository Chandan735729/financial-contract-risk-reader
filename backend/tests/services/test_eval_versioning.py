"""Evaluation run versioning tests — Phase 6 spec SS17, SS19 ("benchmark
versioning" correctness).
"""

from __future__ import annotations

import time

from corpus.eval.versioning import build_run_metadata, results_dir, timestamped_output_path


def test_run_metadata_carries_all_required_versions():
    metadata = build_run_metadata(
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        engine_version="risk_engine_v1",
        embedding_model="test-model",
    )
    assert metadata.taxonomy_version == "taxonomy_v1"
    assert metadata.corpus_version == "corpus_v1"
    assert metadata.engine_version == "risk_engine_v1"
    assert metadata.embedding_model == "test-model"
    assert metadata.benchmark_version  # non-empty
    assert metadata.run_timestamp  # non-empty ISO timestamp
    assert metadata.git_commit  # "unknown" or a real sha, never empty/None


def test_run_metadata_to_dict_is_json_serializable_shape():
    metadata = build_run_metadata(
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        engine_version="risk_engine_v1",
        embedding_model="test-model",
    )
    d = metadata.to_dict()
    assert set(d.keys()) == {
        "run_timestamp",
        "git_commit",
        "git_dirty",
        "taxonomy_version",
        "corpus_version",
        "engine_version",
        "embedding_model",
        "benchmark_version",
    }


def test_results_dir_exists_and_is_a_directory():
    d = results_dir()
    assert d.exists()
    assert d.is_dir()


def test_timestamped_output_path_never_collides_across_runs():
    metadata_a = build_run_metadata(
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        engine_version="risk_engine_v1",
        embedding_model="test-model",
    )
    time.sleep(0.01)
    metadata_b = build_run_metadata(
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        engine_version="risk_engine_v1",
        embedding_model="test-model",
    )
    path_a = timestamped_output_path("test_run", metadata_a)
    path_b = timestamped_output_path("test_run", metadata_b)
    assert path_a != path_b  # a later run never overwrites an earlier one


def test_timestamped_output_path_is_under_results_dir():
    metadata = build_run_metadata(
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        engine_version="risk_engine_v1",
        embedding_model="test-model",
    )
    path = timestamped_output_path("test_run", metadata)
    assert path.parent == results_dir()
    assert path.name.startswith("test_run_")
    assert path.suffix == ".json"
