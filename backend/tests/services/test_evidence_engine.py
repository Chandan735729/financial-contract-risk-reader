"""Evidence Engine tests — Grounding_and_Evidence_Spec.md SS2, Phase 5 spec
SS22. The most important negative test in this file: a fabricated evidence
span must NEVER be accepted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models import db_models
from app.models.enums import RiskCategory
from app.services.evidence_engine import (
    assemble_and_verify_evidence,
    persist_evidence,
    verify_span,
)
from app.services.risk_rules import RuleMatch
from tests.conftest import make_clause, make_clause_analysis, make_document


@dataclass(frozen=True, slots=True)
class _Entity:
    raw_text: str
    start_char: int
    end_char: int


class TestVerifySpan:
    def test_exact_substring_verifies(self):
        raw = "Borrower shall pay a prepayment penalty of 5%."
        start = raw.index("prepayment penalty")
        end = start + len("prepayment penalty")
        assert verify_span(raw, "prepayment penalty", start, end) is True

    def test_whitespace_normalization(self):
        raw = "Borrower shall pay a\nprepayment   penalty of 5%."
        # Claimed text uses single spaces; actual source has a newline and
        # doubled internal space at the same offsets.
        start = raw.index("prepayment")
        end = raw.index("of") - 1
        assert verify_span(raw, "prepayment   penalty", start, end) is True

    def test_punctuation_normalization(self):
        raw = "The borrower’s obligation is to repay in full."
        start = raw.index("borrower")
        end = start + len("borrower’s")
        assert verify_span(raw, "borrower's", start, end) is True

    def test_wrong_span_offsets_do_not_verify(self):
        raw = "Borrower shall pay a prepayment penalty of 5%."
        # Offsets point at "shall pay a prepay" instead of "prepayment penalty".
        assert verify_span(raw, "prepayment penalty", 10, 29) is False

    def test_fabricated_text_never_verifies(self):
        raw = "Borrower shall pay a prepayment penalty of 5%."
        assert verify_span(raw, "a 50% penalty applies immediately", 0, len(raw)) is False

    def test_offsets_out_of_range_do_not_verify(self):
        raw = "Short clause."
        assert verify_span(raw, "Short clause.", 0, 500) is False

    def test_negative_offsets_do_not_verify(self):
        raw = "Short clause."
        assert verify_span(raw, "Short", -1, 5) is False

    def test_end_before_start_does_not_verify(self):
        raw = "Short clause."
        assert verify_span(raw, "Short", 5, 0) is False

    def test_text_from_another_clause_does_not_verify(self):
        raw = "This clause is about renewal terms."
        other_clause_text = "Borrower shall pay a prepayment penalty of 5%."
        assert verify_span(raw, other_clause_text, 0, len(other_clause_text)) is False

    def test_empty_span_never_verifies(self):
        raw = "Some clause text."
        assert verify_span(raw, "", 0, 0) is False
        assert verify_span(raw, "   ", 0, 3) is False


class TestAssembleAndVerifyEvidence:
    def test_entity_condition_and_rule_candidates_all_verify(self):
        text = "Borrower shall pay a prepayment penalty of 5% if the loan is repaid early."
        entity = _Entity(raw_text="5%", start_char=text.index("5%"), end_char=text.index("5%") + 2)
        rule_match = RuleMatch(
            rule_id="prepayment_penalty",
            risk_category=RiskCategory.FINANCIAL_COST,
            risk_subcategory="prepayment_penalty",
            polarity="positive",
            evidence_text="prepayment penalty",
            start_char=text.index("prepayment penalty"),
            end_char=text.index("prepayment penalty") + len("prepayment penalty"),
        )
        result = assemble_and_verify_evidence(
            text,
            page_number=3,
            entities=[entity],
            trigger="if the loan is repaid early",
            condition_text=None,
            consequence=None,
            rule_matches=[rule_match],
        )
        assert result.unverifiable_count == 0
        sources = {item.source for item in result.verified}
        assert sources == {"entity", "condition", "rule"}
        assert all(item.page_number == 3 for item in result.verified)

    def test_fabricated_entity_span_is_discarded_not_shown(self):
        text = "Borrower shall pay a prepayment penalty of 5%."
        fabricated = _Entity(
            raw_text="50% penalty", start_char=0, end_char=10
        )  # doesn't match at these offsets
        result = assemble_and_verify_evidence(
            text,
            page_number=None,
            entities=[fabricated],
            trigger=None,
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert result.verified == ()
        assert result.unverifiable_count == 1
        assert "entity" in result.diagnostics[0]

    def test_condition_text_not_present_in_raw_text_is_discarded(self):
        # Simulates a condition string that (by some upstream bug) doesn't
        # actually come from this clause's raw_text.
        text = "This clause is short."
        result = assemble_and_verify_evidence(
            text,
            page_number=None,
            entities=[],
            trigger="a phrase from a completely different clause",
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert result.verified == ()
        assert result.unverifiable_count == 1

    def test_empty_candidate_fields_are_skipped_not_fabricated(self):
        result = assemble_and_verify_evidence(
            "Short clause.",
            page_number=None,
            entities=[],
            trigger=None,
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert result.verified == ()
        assert result.unverifiable_count == 0

    def test_duplicate_exact_spans_are_deduplicated(self):
        text = "Borrower shall pay a prepayment penalty of 5%."
        entity = _Entity(raw_text="5%", start_char=text.index("5%"), end_char=text.index("5%") + 2)
        result = assemble_and_verify_evidence(
            text,
            page_number=None,
            entities=[entity, entity],
            trigger=None,
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert len(result.verified) == 1

    def test_overlapping_but_distinct_spans_are_both_kept(self):
        text = "Borrower shall pay a prepayment penalty of 5% if repaid early."
        entity = _Entity(raw_text="5%", start_char=text.index("5%"), end_char=text.index("5%") + 2)
        rule_match = RuleMatch(
            rule_id="prepayment_penalty",
            risk_category=RiskCategory.FINANCIAL_COST,
            risk_subcategory="prepayment_penalty",
            polarity="positive",
            # Deliberately overlaps the entity span above (contains it).
            evidence_text="prepayment penalty of 5%",
            start_char=text.index("prepayment penalty of 5%"),
            end_char=text.index("prepayment penalty of 5%") + len("prepayment penalty of 5%"),
        )
        result = assemble_and_verify_evidence(
            text,
            page_number=None,
            entities=[entity],
            trigger=None,
            condition_text=None,
            consequence=None,
            rule_matches=[rule_match],
        )
        assert len(result.verified) == 2

    def test_multiple_distinct_evidence_spans(self):
        text = "A fee of 5% applies within 30 days if the borrower defaults on any payment obligation."
        e1 = _Entity(raw_text="5%", start_char=text.index("5%"), end_char=text.index("5%") + 2)
        e2 = _Entity(raw_text="30 days", start_char=text.index("30 days"), end_char=text.index("30 days") + 7)
        result = assemble_and_verify_evidence(
            text,
            page_number=1,
            entities=[e1, e2],
            trigger="if the borrower defaults",
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert len(result.verified) == 3


class TestPersistEvidence:
    def _make_analysis(self, db_session):
        doc = make_document()
        clause = make_clause(document_id=doc.id, raw_text="A fee of 5% applies within 30 days.")
        analysis = make_clause_analysis(clause_id=clause.id)
        db_session.add_all([doc, clause, analysis])
        db_session.flush()
        return analysis

    def test_flips_existing_entity_span_to_verified_in_place(self, db_session):
        analysis = self._make_analysis(db_session)
        text = analysis.clause.raw_text
        span = db_models.EvidenceSpan(
            id=uuid.uuid4(),
            clause_analysis_id=analysis.id,
            text="5%",
            start_char=text.index("5%"),
            end_char=text.index("5%") + 2,
            verified=False,
        )
        db_session.add(span)
        db_session.flush()

        entity = _Entity(raw_text="5%", start_char=span.start_char, end_char=span.end_char)
        result = assemble_and_verify_evidence(
            text,
            page_number=None,
            entities=[entity],
            trigger=None,
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        persist_evidence(db_session, analysis, result)
        db_session.commit()

        db_session.refresh(span)
        assert span.verified is True
        all_spans = db_session.query(db_models.EvidenceSpan).filter_by(clause_analysis_id=analysis.id).all()
        assert len(all_spans) == 1  # no duplicate row created

    def test_creates_new_rows_for_condition_sourced_evidence(self, db_session):
        analysis = self._make_analysis(db_session)
        text = analysis.clause.raw_text  # "A fee of 5% applies within 30 days."
        result = assemble_and_verify_evidence(
            text,
            page_number=2,
            entities=[],
            trigger="within 30 days",
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        assert len(result.verified) == 1
        rows = persist_evidence(db_session, analysis, result)
        db_session.commit()

        assert len(rows) == 1
        assert rows[0].text == "within 30 days"
        assert rows[0].verified is True
        assert rows[0].page_number == 2

    def test_unverifiable_condition_text_creates_no_row(self, db_session):
        analysis = self._make_analysis(db_session)
        text = analysis.clause.raw_text
        result = assemble_and_verify_evidence(
            text,
            page_number=2,
            entities=[],
            trigger="if the borrower defaults",  # not a substring of this clause
            condition_text=None,
            consequence=None,
            rule_matches=[],
        )
        rows = persist_evidence(db_session, analysis, result)
        db_session.commit()
        assert len(rows) == 0
