"""Hybrid retrieval tests — Phase 4 spec SS17.

All clause/corpus text is synthetic, written for this test suite only.
"""

from __future__ import annotations

from app.models.enums import DocumentType, RiskCategory
from app.services.retrieval_service import index_corpus_patterns, retrieve_matches
from tests.conftest import make_corpus_pattern

TAXONOMY_V1 = "taxonomy_v1"
CORPUS_V1 = "corpus_v1"

_PREPAYMENT_PATTERN = (
    "Borrower shall pay a prepayment penalty equal to 2% of the outstanding "
    "principal if the loan is repaid in full within 24 months of disbursement."
)
_PREPAYMENT_NEGATIVE = "Borrower may make additional principal payments at any time without penalty."
_AUTO_RENEWAL_PATTERN = (
    "This policy will automatically renew for a further period of 12 months "
    "unless the policyholder provides 30 days written notice of cancellation."
)
_FORECLOSURE_PATTERN = "The lender may seize and sell the pledged collateral upon a default by the borrower."
_ARBITRATION_PATTERN = (
    "Any dispute arising under this agreement shall be resolved exclusively through binding arbitration."
)


def _seed_default_corpus(db):
    patterns = [
        make_corpus_pattern(
            pattern_text=_PREPAYMENT_PATTERN,
            risk_category=RiskCategory.FINANCIAL_COST,
            risk_subcategory="prepayment_penalty",
            source="scraped_indian",
            is_negative_example=False,
        ),
        make_corpus_pattern(
            pattern_text=_PREPAYMENT_NEGATIVE,
            risk_category=RiskCategory.FINANCIAL_COST,
            risk_subcategory="prepayment_penalty",
            source="scraped_indian",
            is_negative_example=True,
        ),
        make_corpus_pattern(
            pattern_text=_AUTO_RENEWAL_PATTERN,
            risk_category=RiskCategory.RENEWAL,
            risk_subcategory="auto_renewal",
            source="scraped_indian",
        ),
        make_corpus_pattern(
            pattern_text=_FORECLOSURE_PATTERN,
            risk_category=RiskCategory.DEFAULT,
            risk_subcategory="foreclosure",
            source="scraped_indian",
        ),
        make_corpus_pattern(
            pattern_text=_ARBITRATION_PATTERN,
            risk_category=RiskCategory.LOSS_OF_RIGHTS,
            risk_subcategory="arbitration",
            source="cuad",
        ),
    ]
    db.add_all(patterns)
    db.commit()
    return patterns


def _retrieve(text, db, embedding_service, vector_store, **overrides):
    kwargs = dict(
        db=db,
        embedding_service=embedding_service,
        vector_store=vector_store,
        document_type=DocumentType.LOAN,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
        top_k=5,
        min_similarity_floor=0.3,
        min_lexical_floor=0.1,
    )
    kwargs.update(overrides)
    return retrieve_matches(text, **kwargs)


# 1. exact known risky clause -------------------------------------------------
def test_exact_known_risky_clause_retrieves_top_match(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(_PREPAYMENT_PATTERN, db_session, embedding_service, vector_store)
    assert result.has_signal
    assert result.matches[0].risk_subcategory == "prepayment_penalty"
    assert result.matches[0].similarity_score > 0.95


# 2. paraphrased risky clause --------------------------------------------------
def test_paraphrased_risky_clause_still_matches(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    paraphrase = "If the borrower pays off the loan early, within two years of taking it out, a 2% early payoff fee applies."
    result = _retrieve(paraphrase, db_session, embedding_service, vector_store)
    assert result.has_signal
    assert any(m.risk_subcategory == "prepayment_penalty" for m in result.matches)


# 3. lexical-only match ---------------------------------------------------------
def test_lexical_only_match_surfaces_via_shared_terms(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    # Deliberately keyword-heavy, semantically odd phrasing so dense
    # similarity is weak but exact-term overlap (arbitration/dispute) is strong.
    text = "arbitration arbitration dispute dispute resolved binding"
    result = _retrieve(text, db_session, embedding_service, vector_store, min_similarity_floor=0.9)
    lexical_hits = [m for m in result.matches if m.found_by_lexical]
    assert any(m.risk_subcategory == "arbitration" for m in lexical_hits)


# 4. semantic-only match -----------------------------------------------------------
def test_semantic_only_match_when_no_shared_vocabulary(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    # No literal word overlap with the foreclosure pattern's vocabulary
    # ("seize", "sell", "collateral", "pledged") but same substantive meaning.
    text = "Upon the customer defaulting, the financial institution is entitled to repossess and dispose of the secured asset."
    result = _retrieve(text, db_session, embedding_service, vector_store, min_lexical_floor=0.99)
    dense_hits = [m for m in result.matches if m.found_by_dense]
    assert any(m.risk_subcategory == "foreclosure" for m in dense_hits)


# 5. same-category match -----------------------------------------------------------
def test_same_category_match_ranks_above_unrelated_category(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        "A late payment fee of 2% applies for any overdue installment.",
        db_session,
        embedding_service,
        vector_store,
    )
    assert result.has_signal
    top = result.matches[0]
    assert top.risk_category == "financial_cost"


# 6. wrong-category near match ------------------------------------------------------
def test_wrong_category_near_match_preserves_its_own_category_not_forced(
    db_session, embedding_service, vector_store
):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    # Mentions "renew" (renewal vocabulary) but is actually about arbitration.
    result = _retrieve(
        "Any dispute shall be renewed through binding arbitration proceedings only.",
        db_session,
        embedding_service,
        vector_store,
    )
    assert result.has_signal
    # Retrieval must report the pattern's *actual* category, never silently
    # relabel it to match the query's incidental vocabulary.
    categories = {m.risk_category for m in result.matches}
    assert "loss_of_rights" in categories


# 7. document-type filtering ------------------------------------------------------------
def test_document_type_filtering_excludes_inapplicable_category(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    # `default`/foreclosure is loan-only (Risk_Taxonomy_and_Labeling_Spec.md SS1.2)
    # — must never surface for an insurance document.
    result = _retrieve(
        _FORECLOSURE_PATTERN,
        db_session,
        embedding_service,
        vector_store,
        document_type=DocumentType.INSURANCE,
    )
    assert not any(m.risk_category == "default" for m in result.matches)
    assert result.document_type_filter_applied is True


def test_document_type_filtering_keeps_applicable_category(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        _AUTO_RENEWAL_PATTERN,
        db_session,
        embedding_service,
        vector_store,
        document_type=DocumentType.INSURANCE,
    )
    assert any(m.risk_category == "renewal" for m in result.matches)


# 8. unknown document type ---------------------------------------------------------------
def test_unknown_document_type_applies_no_filtering(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        _FORECLOSURE_PATTERN, db_session, embedding_service, vector_store, document_type=DocumentType.UNKNOWN
    )
    assert any(m.risk_category == "default" for m in result.matches)
    assert result.document_type_filter_applied is False


# 9. no-match ---------------------------------------------------------------------------------
def test_no_match_returns_explicit_no_signal_not_a_fake_match(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        "The parties shall exchange holiday greetings annually on national festival days.",
        db_session,
        embedding_service,
        vector_store,
        min_similarity_floor=0.25,
        min_lexical_floor=0.25,
    )
    assert result.has_signal is False
    assert result.matches == ()


# 10. empty corpus -------------------------------------------------------------------------------
def test_empty_corpus_returns_no_signal_not_an_exception(db_session, embedding_service, vector_store):
    result = _retrieve(_PREPAYMENT_PATTERN, db_session, embedding_service, vector_store)
    assert result.has_signal is False
    assert result.diagnostic is not None


def test_index_corpus_patterns_handles_empty_corpus(db_session, embedding_service, vector_store):
    count = index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    assert count == 0


# 11. corpus version mismatch ------------------------------------------------------------------------
def test_corpus_version_mismatch_never_mixes_versions(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)  # all seeded as corpus_v1
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        _PREPAYMENT_PATTERN, db_session, embedding_service, vector_store, corpus_version="corpus_v2"
    )
    assert result.has_signal is False
    assert result.diagnostic is not None
    assert result.corpus_version == "corpus_v2"  # reports what was *requested*, not what exists


# 12. taxonomy version mismatch --------------------------------------------------------------------------
def test_taxonomy_version_mismatch_never_mixes_versions(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)  # all seeded as taxonomy_v1
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(
        _PREPAYMENT_PATTERN, db_session, embedding_service, vector_store, taxonomy_version="taxonomy_v2"
    )
    assert result.has_signal is False
    assert result.diagnostic is not None


# 13. negative example ------------------------------------------------------------------------------------
def test_negative_example_surfaced_with_its_flag_set(db_session, embedding_service, vector_store):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    result = _retrieve(_PREPAYMENT_NEGATIVE, db_session, embedding_service, vector_store)
    assert result.has_signal
    negative_matches = [m for m in result.matches if m.is_negative_example]
    assert len(negative_matches) >= 1
    assert negative_matches[0].risk_subcategory == "prepayment_penalty"


# 14. negated-risk clause ---------------------------------------------------------------------------------------
def test_negated_risk_clause_surfaces_both_topic_and_negation_signal(
    db_session, embedding_service, vector_store
):
    _seed_default_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )
    # A clause that mentions prepayment but explicitly negates the penalty —
    # retrieval must not silently drop the topic match, and must preserve
    # enough information (is_negative_example on whichever pattern matched)
    # for Phase 5 to tell "prepayment" apart from "prepayment without penalty".
    clause_text = "Borrower may prepay the loan in full at any time without incurring any prepayment penalty."
    result = _retrieve(clause_text, db_session, embedding_service, vector_store)
    assert result.has_signal
    subcategories = {m.risk_subcategory for m in result.matches}
    assert "prepayment_penalty" in subcategories
    # The final safe/risky decision is explicitly NOT made here — this test
    # only proves the signal (both the positive and negative pattern) is
    # preserved, per Phase 4 spec SS15/SS16.
    assert any(m.is_negative_example for m in result.matches)


class TestNeverMergesScores:
    def test_similarity_and_lexical_scores_kept_independent(
        self, db_session, embedding_service, vector_store
    ):
        _seed_default_corpus(db_session)
        index_corpus_patterns(
            db_session,
            embedding_service=embedding_service,
            vector_store=vector_store,
            taxonomy_version=TAXONOMY_V1,
            corpus_version=CORPUS_V1,
        )
        result = _retrieve(_PREPAYMENT_PATTERN, db_session, embedding_service, vector_store)
        for match in result.matches:
            assert hasattr(match, "similarity_score")
            assert hasattr(match, "lexical_score")
            assert not hasattr(match, "combined_similarity")
