"""Synthetic retrieval benchmark — Dataset_and_Evaluation_Spec.md SS5
("Retrieval: Recall@1, Recall@3, Recall@5 ... MRR"), Phase 4 spec SS17/SS24.

**Synthetic and hand-authored, not the real-world benchmark
Dataset_and_Evaluation_Spec.md SS4 requires** (a labeled corpus built from
real permission-cleared source documents with inter-annotator agreement
checking). Useful for (a) proving the retrieval evaluation harness computes
correctly and (b) a directional regression check on the hybrid retrieval
implementation against known structural patterns — not a production
accuracy claim. See docs/PROVISIONAL_DECISIONS.md "Phase 4: retrieval
evaluation is synthetic-only".

Each `BenchmarkQuery` names the corpus pattern index (`gold_index`) that a
correctly working retrieval system should surface for it — computable by
construction since both are hand-authored together.
"""

from __future__ import annotations

from dataclasses import dataclass

CORPUS_PATTERNS: list[dict] = [
    {
        "text": (
            "Borrower shall pay a prepayment penalty equal to 2% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        ),
        "risk_category": "financial_cost",
        "risk_subcategory": "prepayment_penalty",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "Borrower may make additional principal payments at any time without penalty.",
        "risk_category": "financial_cost",
        "risk_subcategory": "prepayment_penalty",
        "source": "scraped_indian",
        "is_negative_example": True,
    },
    {
        "text": (
            "This policy will automatically renew for a further period of 12 months "
            "unless the policyholder provides 30 days written notice of cancellation."
        ),
        "risk_category": "renewal",
        "risk_subcategory": "auto_renewal",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "The lender may seize and sell the pledged collateral upon a default by the borrower.",
        "risk_category": "default",
        "risk_subcategory": "foreclosure",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "Any dispute arising under this agreement shall be resolved exclusively through binding arbitration.",
        "risk_category": "loss_of_rights",
        "risk_subcategory": "arbitration",
        "source": "cuad",
        "is_negative_example": False,
    },
    {
        "text": "The insurer shall not be liable for any claim arising from a pre-existing medical condition.",
        "risk_category": "insurance",
        "risk_subcategory": "exclusion",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "A waiting period of 90 days applies before coverage under this policy becomes effective.",
        "risk_category": "insurance",
        "risk_subcategory": "waiting_period",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "Interest on the outstanding balance shall accrue at a variable rate determined by the lender.",
        "risk_category": "interest_repayment",
        "risk_subcategory": "variable_interest",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
    {
        "text": "The Borrower waives any right to a jury trial in connection with this agreement.",
        "risk_category": "loss_of_rights",
        "risk_subcategory": "waiver",
        "source": "cuad",
        "is_negative_example": False,
    },
    {
        "text": "An early termination fee equal to one month's payment applies if this agreement is terminated before the end of the term.",
        "risk_category": "termination",
        "risk_subcategory": "early_termination_fee",
        "source": "scraped_indian",
        "is_negative_example": False,
    },
]


@dataclass(frozen=True)
class BenchmarkQuery:
    text: str
    gold_index: int
    kind: str  # "exact" | "paraphrase"


BENCHMARK_QUERIES: list[BenchmarkQuery] = [
    BenchmarkQuery(text=CORPUS_PATTERNS[0]["text"], gold_index=0, kind="exact"),
    BenchmarkQuery(
        text="If the borrower pays off the loan early, within two years of taking it out, a 2% early payoff fee applies.",
        gold_index=0,
        kind="paraphrase",
    ),
    BenchmarkQuery(text=CORPUS_PATTERNS[2]["text"], gold_index=2, kind="exact"),
    BenchmarkQuery(
        text="Unless the policyholder gives 30 days notice, this insurance policy renews itself for another year automatically.",
        gold_index=2,
        kind="paraphrase",
    ),
    BenchmarkQuery(
        text="Upon the customer defaulting, the financial institution is entitled to repossess and dispose of the secured asset.",
        gold_index=3,
        kind="paraphrase",
    ),
    BenchmarkQuery(text=CORPUS_PATTERNS[4]["text"], gold_index=4, kind="exact"),
    BenchmarkQuery(
        text="Claims relating to any condition the policyholder had before buying this insurance are excluded from coverage.",
        gold_index=5,
        kind="paraphrase",
    ),
    BenchmarkQuery(text=CORPUS_PATTERNS[6]["text"], gold_index=6, kind="exact"),
    BenchmarkQuery(
        text="The interest rate applicable to the remaining loan balance is not fixed and may be changed by the lender.",
        gold_index=7,
        kind="paraphrase",
    ),
    BenchmarkQuery(text=CORPUS_PATTERNS[9]["text"], gold_index=9, kind="exact"),
]
