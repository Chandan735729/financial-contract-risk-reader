# Frontend Specification v2 — Financial Contract Risk Reader

**Cross-references:** the original Frontend Specification Document's design system (colors, typography, component base styles) still applies and is not repeated here. This file covers what v2's richer risk model changes about information architecture and UI behavior.

---

## 1. Information Architecture Changes

The report is no longer a two-state (flagged/unflagged) list — it's a **four-state** list: `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`. `UNKNOWN` must read as "the system doesn't have enough evidence," visually distinct from both "risky" and "safe" — not a muted version of either.

## 2. Risk Level Color/Visual Mapping (extends the v1 palette)

| Level | Color token (from original design system) | Additional treatment |
|---|---|---|
| `HIGH` | `risk-red` | Solid margin flag, full card tint |
| `MEDIUM` | `risk-amber` | Solid margin flag, full card tint |
| `LOW` | `risk-green` | Thin margin flag, no tint (per v1 spec) |
| `UNKNOWN` | New token: `risk-unknown` = `#7C8A9C` (reuses `ink-400` from the existing neutral palette — deliberately *not* a new saturated color, since `UNKNOWN` is an absence of a confident risk color, not a fourth risk color) | Dashed margin flag (not solid) to visually signal "undetermined" rather than "safe" or "risky"; icon: a question mark or similar, never reuses the check/warning/alert icon shapes used for the other three |

**Rule:** `UNKNOWN` must never visually read as calmer or safer than `LOW` — the dashed-border treatment specifically avoids this, since a solid thin green-adjacent bar could be misread as "mostly fine."

## 3. Confidence UI

Every `HIGH`/`MEDIUM`/`LOW` clause card shows a confidence indicator distinct from the risk-level badge — e.g., a small labeled value ("Confidence: High / Medium / Low," backed by the underlying `confidence_score`) placed next to, not blended into, the risk badge. Confidence is never represented using the same red/amber/green color system as risk level (per the original design system's rule that those three colors mean risk and nothing else) — use a neutral scale (e.g., filled dots/bars in `ink-700`/`ink-400`) instead.

## 4. Upload & Processing Flow

Unchanged structurally from v1 (dropzone → validation → processing status with live per-stage polling), with one addition: the processing status view now reflects the v2 pipeline's stages (parsing → segmenting → clause understanding → risk engine → generating explanations → grounding check) rather than the shorter v1 list, giving the user a more accurate sense of what's happening and why it may take longer for complex documents.

## 5. Report Page & Clause Cards

Extends the v1 `ClauseCard` component:

- **Header row:** risk category tag + clause reference (unchanged from v1) + new confidence indicator (Section 3).
- **Evidence block (new):** below the plain-language explanation, a labeled "Evidence" section showing the highlighted excerpt(s) of original clause text that support the claim, with extracted financial entities (amounts, percentages, rates) visually distinguished within the excerpt (e.g., bold + `signal-blue` underline, not a risk color, since these are facts, not risk judgments themselves).
- **Explanation-unavailable state:** when the grounding guard fails (Grounding_and_Evidence_Spec.md §5), the card still shows risk level, category, confidence, and evidence — only the plain-language explanation field is replaced with the defined fallback message. The card must not look broken or incomplete; the evidence and structured data are the trustworthy core, and the UI should communicate that.
- **`UNKNOWN` clause card:** shows the abstain reason in plain language (e.g., "We couldn't find enough evidence in this clause to assess it confidently") rather than an empty risk section.

## 6. Summary Bar

Extends to four counts (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`) instead of three. Default filter view on report load: `HIGH` and `MEDIUM` clauses shown first/expanded, `UNKNOWN` shown but visually separated (e.g., a distinct section beneath the flagged clauses, not interleaved), `LOW` collapsed/available via filter — consistent with the v1 filter bar behavior, extended to the new state.

## 7. Errors

Failure-state messaging inherits the original Security and Access Document's error handling guide (each backend failure type maps to a specific, non-technical user message) — v2 adds new failure types from the extended pipeline (entity extraction failure, condition extraction failure, grounding guard failure) which are handled at the *clause* level, not the document level: one clause's extraction failure does not prevent the rest of the report from rendering (Technical_Architecture_v2.md §8).

## 8. Accessibility

Unchanged baseline from the original Frontend Specification Document (Section A.6), with one addition: the `UNKNOWN` state's dashed-border treatment must still meet contrast requirements against both `paper-000` and `paper-100` backgrounds, and must be distinguishable from `LOW` by users who rely on high-contrast or grayscale rendering — verify specifically, since this is a new state not covered by the original color-contrast audit.

## 9. Visual Design

No changes to the core design system (color palette, typography, spacing, button/input/modal styles) established in the original Frontend Specification Document — v2 is additive at the component/state level only, specifically to avoid design fragmentation between the two versions.
