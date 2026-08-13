"""Internal Generation/Grounding contract — Grounding_and_Evidence_Spec.md
SS3-5, Technical_Architecture_v2.md SS2 (Generation Service -> Grounding
Guard -> Final Report).

Shared between `generation_service.py` (producer) and `grounding_guard.py`
(consumer) in a separate module — same reason as `segmentation_models.py` —
to avoid a producer/consumer import cycle: `generation_service` calls
`grounding_guard.grounding_guard(...)`, so the shared value types cannot
live in either module without the other importing back.

Frozen dataclasses on purpose — this contract never crosses a process/API
boundary and is never serialized directly (the persisted form is
`ClauseAnalysisORM.explanation`/`explanation_grounded`, written by the
pipeline-wiring layer, not these types).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    """One discrete, checkable fact from the LLM's structured output —
    Grounding_and_Evidence_Spec.md SS3 point 1: "Parse the LLM's structured
    output into discrete claims." The LLM is asked to decompose its own
    `explanation` text into this list itself (see `generation_service`'s
    prompt), rather than this codebase re-deriving claims from free text via
    NLP sentence-splitting after the fact — a more reliable decomposition
    than guessing sentence boundaries, and the literal mechanism SS3 point 1
    describes.
    """

    text: str
    claim_type: str
    # References into the prompt's `E<n>`/`N<n>` evidence-span/entity labels
    # (see `generation_service._build_user_prompt`). A *hint* only — the
    # model can hallucinate or mis-cite an ID, so `grounding_guard` never
    # trusts this list on its own; it independently re-verifies `text`
    # against the clause's actual evidence (Grounding_and_Evidence_Spec.md
    # SS4: checks "supported_by_evidence", not "claims to be supported").
    supporting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GeneratedExplanation:
    """The LLM's structured response for one clause, converted to the
    in-memory shape `grounding_guard.grounding_guard` consumes
    (Grounding_and_Evidence_Spec.md SS4: `generated: GeneratedExplanation`).
    """

    text: str
    claims: tuple[GeneratedClaim, ...]


@dataclass(frozen=True, slots=True)
class GuardResult:
    """Grounding_and_Evidence_Spec.md SS4's `GuardResult`. `passed=False`
    with a non-empty `unsupported_claims` means the *whole* explanation is
    rejected — SS7 "Partial support case": "a single unsupported claim
    disqualifies display, since users can't tell which parts to trust
    otherwise." There is no partial-credit variant of this type.
    """

    passed: bool
    unsupported_claims: tuple[GeneratedClaim, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    """What `generation_service.generate_explanation` hands back to the
    pipeline-wiring layer — already resolved to exactly one of the three
    persisted states documented in `generation_config`'s module docstring
    (skipped is not represented here; the wiring layer decides that before
    ever calling `generate_explanation`).

    `failure_category` is a short, safe-to-log machine label
    (Security_and_Privacy_v2.md SS6) — never free text, and never `None`
    when `explanation_grounded` is `False`.
    """

    explanation: str | None
    explanation_grounded: bool
    model_version: str
    attempts: int
    failure_category: str | None
