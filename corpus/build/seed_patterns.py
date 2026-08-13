"""PHASE_6.5 synthetic seed corpus — docs/PROVISIONAL_DECISIONS.md P6.8.

**This is NOT the real-world reference corpus** `Dataset_and_Evaluation_Spec.md`
SS1 calls for (a CUAD subset + permissioned, provenance-tracked scraping of
Indian loan/insurance T&Cs). That sourcing work was scoped in the docs and
never executed (see `corpus/README.md`) — attempting it inside this phase
would mean either indiscriminate scraping or committing text without a clear
license/provenance trail, both explicitly disallowed. Instead, this module
seeds a small, honestly-labeled, taxonomy-aligned corpus (`source =
"synthetic_seed"`) so the retrieval pipeline (`retrieval_service.py`,
`ChromaVectorStore`) has something real to index and query end-to-end —
exercising the *pipeline*, not claiming production-quality coverage.

Every entry here is hand-authored specifically for this corpus, with
deliberately different wording from every DEV/TEST/ADVERSARIAL fixture and
every rule-test example elsewhere in this repo — this corpus must never be
inflated by copying eval fixtures into it (that would make retrieval
"succeed" only by finding its own test data, not by generalizing).

Covers the 13 subcategories `risk_rules.py` has a deterministic rule for —
one positive and one confirmed-negative ("is_negative_example=True") pattern
each, per Risk_Taxonomy_and_Labeling_Spec.md SS4's positive/negative example
convention. The remaining ~22 taxonomy subcategories have no rule and no
seed pattern yet — genuinely uncovered, not silently implied otherwise (see
`corpus/README.md` for the explicit coverage table).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import RiskCategory  # noqa: E402

SOURCE_SYNTHETIC_SEED = "synthetic_seed"
SEED_TAXONOMY_VERSION = "taxonomy_v1"
SEED_CORPUS_VERSION = "corpus_v1"


@dataclass(frozen=True, slots=True)
class CorpusPatternSeed:
    pattern_text: str
    risk_category: RiskCategory
    risk_subcategory: str
    is_negative_example: bool = False
    # Hand-authored, unambiguous examples — a legitimate 1.0, not a
    # fabricated precision claim (these aren't inferred/model-scored).
    annotator_confidence: float = 1.0
    source: str = SOURCE_SYNTHETIC_SEED
    taxonomy_version: str = SEED_TAXONOMY_VERSION
    corpus_version: str = SEED_CORPUS_VERSION


SEED_PATTERNS: tuple[CorpusPatternSeed, ...] = (
    # -- FINANCIAL_COST / prepayment_penalty --
    CorpusPatternSeed(
        pattern_text=(
            "If the borrower settles the outstanding loan amount before the scheduled maturity "
            "date, a prepayment charge of up to 4% of the remaining principal will be levied."
        ),
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "The borrower is permitted to make partial or full prepayments toward the loan at "
            "any time without incurring any prepayment charge."
        ),
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        is_negative_example=True,
    ),
    # -- RENEWAL / auto_renewal --
    CorpusPatternSeed(
        pattern_text=(
            "Unless the policyholder submits a written cancellation request at least 30 days "
            "before the expiry date, this policy will renew automatically for a further "
            "one-year term."
        ),
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="auto_renewal",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "This membership does not renew automatically; it lapses at the end of the term "
            "unless the member actively opts to renew it."
        ),
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="auto_renewal",
        is_negative_example=True,
    ),
    # -- LOSS_OF_RIGHTS / arbitration --
    CorpusPatternSeed(
        pattern_text=(
            "Any dispute, controversy, or claim arising out of this agreement shall be finally "
            "settled by binding arbitration, and each party expressly waives its right to a "
            "jury trial."
        ),
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="arbitration",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "Nothing in this agreement requires arbitration, and neither party waives its "
            "right to bring a claim before a court of competent jurisdiction."
        ),
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="arbitration",
        is_negative_example=True,
    ),
    # -- DEFAULT / acceleration --
    CorpusPatternSeed(
        pattern_text=(
            "If the borrower fails to remit two or more consecutive monthly installments, the "
            "lender may declare the entire outstanding balance immediately due and payable "
            "through acceleration."
        ),
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="acceleration",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "A single missed installment does not trigger acceleration of the loan; the lender "
            "will provide a cure period before pursuing any such remedy."
        ),
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="acceleration",
        is_negative_example=True,
    ),
    # -- TERMINATION / early_termination_fee --
    CorpusPatternSeed(
        pattern_text=(
            "Should this agreement be terminated by the customer prior to the end of the "
            "initial term, an early termination charge equal to the remaining monthly fees "
            "shall become payable."
        ),
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="early_termination_fee",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "This agreement may be terminated by either party at any time prior to its natural "
            "expiry without any early termination charge."
        ),
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="early_termination_fee",
        is_negative_example=True,
    ),
    # -- INSURANCE / exclusion --
    CorpusPatternSeed(
        pattern_text=(
            "Coverage under this policy excludes any loss or claim resulting directly or "
            "indirectly from war, nuclear hazard, or intentional self-inflicted injury."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="exclusion",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "This policy does not exclude coverage for accidental injuries sustained during "
            "normal daily activities."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="exclusion",
        is_negative_example=True,
    ),
    # -- INSURANCE / waiting_period --
    CorpusPatternSeed(
        pattern_text=(
            "A waiting period of 180 days from the policy commencement date applies before "
            "coverage for any pre-existing illness becomes effective."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="waiting_period",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "No waiting period applies to emergency hospitalization claims filed under this "
            "policy; coverage begins immediately upon policy issuance."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="waiting_period",
        is_negative_example=True,
    ),
    # -- INSURANCE / deductible --
    CorpusPatternSeed(
        pattern_text=(
            "For each claim submitted under this policy, a deductible amount of Rs. 2,500 is "
            "payable by the policyholder before the insurer's payment obligation begins."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="deductible",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "This policy carries no deductible; the insurer's obligation to pay a covered "
            "claim begins from the first rupee of loss."
        ),
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="deductible",
        is_negative_example=True,
    ),
    # -- INTEREST_REPAYMENT / rate_change --
    CorpusPatternSeed(
        pattern_text=(
            "The applicable interest rate on this facility is variable and may be revised "
            "upward by the lender at its discretion in line with changes to the benchmark "
            "lending rate."
        ),
        risk_category=RiskCategory.INTEREST_REPAYMENT,
        risk_subcategory="rate_change",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "The interest rate applicable to this loan is fixed for the entire tenure and will "
            "not change regardless of market conditions."
        ),
        risk_category=RiskCategory.INTEREST_REPAYMENT,
        risk_subcategory="rate_change",
        is_negative_example=True,
    ),
    # -- LOSS_OF_RIGHTS / waiver (standalone) --
    CorpusPatternSeed(
        pattern_text=(
            "By signing this agreement, the customer waives any right to participate in a "
            "class action lawsuit against the company arising from this agreement."
        ),
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="waiver",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "No provision of this agreement requires the customer to waive any statutory "
            "right, including the right to participate in a class action."
        ),
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="waiver",
        is_negative_example=True,
    ),
    # -- DEFAULT / cross_default --
    CorpusPatternSeed(
        pattern_text=(
            "A default by the borrower under any other credit facility or loan agreement with "
            "any lender shall automatically constitute a cross-default under this agreement, "
            "entitling the lender to accelerate repayment."
        ),
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="cross_default",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "A default under a separate, unrelated credit facility held by the borrower does "
            "not, on its own, constitute a default or cross-default under this agreement."
        ),
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="cross_default",
        is_negative_example=True,
    ),
    # -- RENEWAL / renewal_fee --
    CorpusPatternSeed(
        pattern_text=(
            "A non-refundable renewal fee of Rs. 750 is payable by the policyholder at the "
            "commencement of each renewed policy term."
        ),
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="renewal_fee",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "No renewal fee is charged to existing policyholders who choose to continue their "
            "coverage into a new policy term."
        ),
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="renewal_fee",
        is_negative_example=True,
    ),
    # -- TERMINATION / unilateral_termination_right --
    CorpusPatternSeed(
        pattern_text=(
            "The company reserves the right to terminate this agreement at its sole "
            "discretion, with or without cause, upon written notice to the customer."
        ),
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="unilateral_termination_right",
    ),
    CorpusPatternSeed(
        pattern_text=(
            "Termination of this agreement by the company requires the prior written consent "
            "of the customer and cannot occur unilaterally."
        ),
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="unilateral_termination_right",
        is_negative_example=True,
    ),
)
