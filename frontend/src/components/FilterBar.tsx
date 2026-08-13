"use client";

// Filter controls — Phase 9 spec §14. Checkboxes (not a single-select, so
// multiple risk levels can be shown together) plus a category dropdown.
// Accessible: each control has a visible, associated label; state is
// never conveyed by color alone (checked/unchecked is a real form state).

import { RiskCategory, RiskLevel } from "@/types/enums";
import { formatCategory } from "@/lib/formatCategory";
import styles from "./FilterBar.module.css";

const LEVEL_OPTIONS = [RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.UNKNOWN];

export function FilterBar({
  selectedLevels,
  onToggleLevel,
  availableCategories,
  selectedCategory,
  onCategoryChange,
}: {
  selectedLevels: ReadonlySet<RiskLevel>;
  onToggleLevel: (level: RiskLevel) => void;
  availableCategories: RiskCategory[];
  selectedCategory: RiskCategory | "all";
  onCategoryChange: (category: RiskCategory | "all") => void;
}) {
  return (
    <fieldset className={styles.wrapper}>
      <legend className={styles.legend}>Filter clauses</legend>
      <div className={styles.levelGroup}>
        {LEVEL_OPTIONS.map((level) => {
          const id = `filter-level-${level}`;
          return (
            <label key={level} htmlFor={id} className={styles.checkboxLabel}>
              <input
                id={id}
                type="checkbox"
                checked={selectedLevels.has(level)}
                onChange={() => onToggleLevel(level)}
              />
              {level.charAt(0) + level.slice(1).toLowerCase()}
            </label>
          );
        })}
      </div>

      {availableCategories.length > 0 && (
        <div className={styles.categoryGroup}>
          <label htmlFor="filter-category" className={styles.selectLabel}>
            Category
          </label>
          <select
            id="filter-category"
            value={selectedCategory}
            onChange={(event) => onCategoryChange(event.target.value as RiskCategory | "all")}
          >
            <option value="all">All categories</option>
            {availableCategories.map((category) => (
              <option key={category} value={category}>
                {formatCategory(category)}
              </option>
            ))}
          </select>
        </div>
      )}
    </fieldset>
  );
}
