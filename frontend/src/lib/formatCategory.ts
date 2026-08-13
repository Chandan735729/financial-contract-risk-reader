import { RiskCategory } from "@/types/enums";

const LABELS: Record<RiskCategory, string> = {
  [RiskCategory.FINANCIAL_COST]: "Financial cost",
  [RiskCategory.DEFAULT]: "Default",
  [RiskCategory.RENEWAL]: "Renewal",
  [RiskCategory.LOSS_OF_RIGHTS]: "Loss of rights",
  [RiskCategory.INSURANCE]: "Insurance",
  [RiskCategory.INTEREST_REPAYMENT]: "Interest & repayment",
  [RiskCategory.TERMINATION]: "Termination",
  [RiskCategory.OTHER]: "Other",
};

export function formatCategory(category: RiskCategory | null): string | null {
  return category ? LABELS[category] : null;
}

/** `risk_subcategory` is a free-text string from the backend (no shared
 * enum — see backend/app/models/db_models.py's `FinancialEntity.entity_type`
 * precedent for the same design), so this only does cosmetic
 * snake_case -> Title Case formatting, never a lookup table. */
export function formatSubcategory(subcategory: string | null): string | null {
  if (!subcategory) return null;
  return subcategory
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
