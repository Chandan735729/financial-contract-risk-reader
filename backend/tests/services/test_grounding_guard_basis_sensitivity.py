"""Grounding Guard basis-sensitivity check — Phase 11
(docs/PROVISIONAL_DECISIONS.md P11.6, closing the "basis-substitution"
limitation the Phase 10 security audit found and
`tests/services/test_explanation_fidelity.py::test_18_semantically_similar_unsupported_claim_now_caught`
now confirms fixed).

Eight adversarial/regression categories, each with hand-verified
significant-word arithmetic (see the inline overlap notes) so a future
change to `_BASIS_OVERLAP_FLOOR`/`_BASIS_WINDOW_WORDS` can be checked
against a worked-out expectation, not just a pass/fail:

  1. Percentage-of-X basis substitution (the documented example's shape)
  2. Currency-amount per-X (temporal) basis substitution
  3. Time-period-of-X basis substitution
  4. Interest-rate per-annum-on-X basis substitution
  5. Partial substitution: one of two numbers in a claim has its basis
     swapped, the other doesn't -- the whole claim must still fail
  6. Legitimate synonym-paraphrase basis must still pass (non-regression)
  7. A claim with no "of"/"per" construct at all must be unaffected
     (non-regression -- this check must never fire when there is nothing
     for it to check)
  8. An invented basis for a number the source states with no "of"/"per"
     governing phrase at all must fail closed (the source never confirms
     *any* basis for that number, so a claim inventing one is unsupported)
"""

from __future__ import annotations

from app.models.enums import RiskLevel
from app.models.schemas import FinancialEntity
from app.services.generation_models import GeneratedClaim
from app.services.grounding_guard import supported_by_evidence


def _supported(
    raw_text: str,
    claim_text: str,
    *,
    entities: tuple[FinancialEntity, ...] = (),
    risk_level: RiskLevel = RiskLevel.HIGH,
) -> bool:
    """Exercises `supported_by_evidence` directly (same pattern as
    `tests/services/test_grounding_guard.py`) rather than constructing a
    full `ClauseAnalysis` -- the function under test only ever reads
    `evidence_spans`/`financial_entities`/`raw_text`/`risk_level`, and a
    full `ClauseAnalysis` for a HIGH-risk clause requires at least one
    verified `EvidenceSpan`, which is irrelevant machinery for what this
    file is testing. No evidence spans are constructed here at all -- per
    the module docstring's check 4/SS3 point 2(c), `raw_text` alone
    already grounds a claim; every case in this file relies on that path.
    """
    claim = GeneratedClaim(text=claim_text, claim_type="risk_summary")
    return supported_by_evidence(claim, (), entities, raw_text, risk_level)


class TestPercentageOfXBasisSubstitution:
    _RAW = (
        "The Borrower shall pay a late fee equal to 3% of the outstanding "
        "loan balance if any installment is not paid within 10 days of "
        "the due date."
    )
    _ENTITIES = (FinancialEntity(type="percentage", value="3", unit="%", raw_text="3%"),)

    def test_substituted_basis_is_rejected(self):
        # Claim window after "3% of ": {borrower, total, monthly, income}.
        # Corpus window after "3% of ": {outstanding, loan, balance, any,
        # installment}. Zero overlap.
        assert (
            _supported(
                self._RAW,
                "The late fee is 3% of the borrower's total monthly income.",
                entities=self._ENTITIES,
            )
            is False
        )

    def test_synonym_paraphrase_of_the_real_basis_still_passes(self):
        # Claim window: {outstanding, balance, loan} -- all three appear in
        # the corpus window too (order-independent set overlap) -> 3/3.
        assert (
            _supported(
                self._RAW,
                "The late fee equals 3% of the outstanding balance on the loan.",
                entities=self._ENTITIES,
            )
            is True
        )


class TestCurrencyPerXBasisSubstitution:
    _RAW = "The Borrower shall pay a late payment fee of $50 per missed installment."
    _ENTITIES = (FinancialEntity(type="amount", value="50", unit="$", raw_text="$50"),)

    def test_substituted_temporal_basis_is_rejected(self):
        # Claim window after "$50 per ": {calendar, year}. Corpus window:
        # {missed, installment}. Zero overlap.
        assert (
            _supported(
                self._RAW,
                "The late payment fee is $50 per calendar year.",
                entities=self._ENTITIES,
            )
            is False
        )

    def test_close_paraphrase_of_the_real_basis_still_passes(self):
        # Claim window: {missed, payment}. Corpus window: {missed,
        # installment}. Overlap 1/2 = 0.5, clears the 0.34 floor.
        assert (
            _supported(
                self._RAW,
                "The late payment fee is $50 per missed payment.",
                entities=self._ENTITIES,
            )
            is True
        )


class TestTimePeriodOfXBasisSubstitution:
    _RAW = (
        "The Borrower must repay the loan in full within 24 months of "
        "the disbursement date, or an acceleration penalty applies."
    )

    def test_substituted_basis_is_rejected(self):
        # Claim window after "24 months of ": {borrower, employment,
        # start, date}. Corpus window: {disbursement, date, acceleration,
        # penalty, applies}. Overlap 1/4 = 0.25, below the 0.34 floor.
        assert (
            _supported(
                self._RAW,
                "The loan must be repaid within 24 months of the borrower's employment start date.",
            )
            is False
        )

    def test_paraphrase_keeping_the_real_basis_still_passes(self):
        # Claim window: {disbursement, date, loan, agreement}. Corpus
        # window: {disbursement, date, acceleration, penalty, applies}.
        # Overlap 2/4 = 0.5.
        assert (
            _supported(
                self._RAW,
                "The loan must be repaid within 24 months of the disbursement date on the loan agreement.",
            )
            is True
        )


class TestInterestRatePerAnnumBasisSubstitution:
    _RAW = "Interest shall accrue at a rate of 8.5% per annum on the outstanding principal balance."
    _ENTITIES = (FinancialEntity(type="rate", value="8.5", unit="%", raw_text="8.5%"),)

    def test_substituted_basis_is_rejected(self):
        # Claim window after "8.5% per ": {annum, borrower, gross,
        # monthly, salary}. Corpus window: {annum, outstanding, principal,
        # balance}. Overlap 1/5 = 0.2, below the floor even though "annum"
        # itself is shared.
        assert (
            _supported(
                self._RAW,
                "The interest rate is 8.5% per annum on the borrower's gross monthly salary.",
                entities=self._ENTITIES,
            )
            is False
        )

    def test_paraphrase_keeping_the_real_basis_still_passes(self):
        # Claim window: {annum, outstanding, balance, loan}. Corpus
        # window: {annum, outstanding, principal, balance}. Overlap
        # 3/4 = 0.75.
        assert (
            _supported(
                self._RAW,
                "The interest rate is 8.5% per annum on the outstanding balance of the loan.",
                entities=self._ENTITIES,
            )
            is True
        )


class TestPartialSubstitutionAcrossMultipleNumbers:
    _RAW = (
        "The Borrower shall pay a prepayment penalty of 4% of the "
        "outstanding principal if the loan is repaid within 18 months of "
        "the disbursement date."
    )
    _ENTITIES = (FinancialEntity(type="percentage", value="4", unit="%", raw_text="4%"),)

    def test_one_substituted_basis_among_several_numbers_still_fails_the_whole_claim(self):
        # The 4%/"outstanding principal" pairing is left correctly stated;
        # only the second number's basis is swapped (disbursement date ->
        # the borrower's account opening date, zero shared significant
        # words beyond "date": {borrower, account, opening, date} vs
        # {disbursement, date} -> 1/4 = 0.25, below the floor). One
        # unsupported basis is enough to fail the whole claim -- same
        # "no partial credit" posture as every other check in this guard.
        assert (
            _supported(
                self._RAW,
                "The prepayment penalty is 4% of the outstanding principal if repaid within 18 months "
                "of the borrower's account opening date.",
                entities=self._ENTITIES,
            )
            is False
        )


class TestNoBasisConstructIsUnaffected:
    _RAW = (
        "The Borrower shall pay a late fee equal to 3% of the outstanding "
        "loan balance if any installment is not paid within 10 days of "
        "the due date."
    )
    _ENTITIES = (FinancialEntity(type="percentage", value="3", unit="%", raw_text="3%"),)

    def test_a_bare_number_claim_with_no_of_or_per_is_judged_only_by_the_existing_checks(self):
        # No "of"/"per" immediately follows "3%" here, so check 5 never
        # activates at all -- this claim is graded purely on checks 1-4,
        # exactly as it would have been before this phase.
        assert _supported(self._RAW, "The borrower must pay a 3% late fee.", entities=self._ENTITIES) is True


class TestInventedBasisForANumberWithNoSourceBasisFailsClosed:
    _RAW = "The Tenant shall pay a security deposit of $2,000, refundable at the end of the lease term."
    _ENTITIES = (FinancialEntity(type="amount", value="2000", unit="$", raw_text="$2,000"),)

    def test_claim_inventing_a_basis_the_source_never_states_is_rejected(self):
        # The source states "$2,000" with no "of"/"per" governing phrase
        # anywhere near it (it's followed by ", refundable..."). A claim
        # that invents one ("per month of rent") asserts a specific
        # relationship the source does not confirm at all -- fail closed,
        # not "no evidence either way so let it through."
        assert (
            _supported(
                self._RAW,
                "The security deposit is $2,000 per month of rent.",
                entities=self._ENTITIES,
            )
            is False
        )
