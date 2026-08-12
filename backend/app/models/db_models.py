"""SQLAlchemy ORM models — API_and_Data_Models.md SS2.

Table shape follows API_and_Data_Models.md SS2 exactly for
`clause_analyses`, `financial_entities`, `evidence_spans`, `matched_patterns`
(these are fully specified there). `documents` and `clauses` extend v1
columns that are not defined anywhere in this repository; only the v2
*additions* named in SS2 are authoritative — their v1 base columns are
minimal, provisional definitions. `users`, `processing_jobs`, and the base
shape of `corpus_patterns` are referenced as "unchanged from v1" but no v1
definition exists in this repository at all, so they are minimal provisional
tables.

Every provisional decision below is documented in
`docs/PROVISIONAL_DECISIONS.md` and marked PROVISIONAL_V2 in comments here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID
from app.models.enums import (
    ConfidenceLevel,
    DocumentType,
    ProcessingStage,
    RiskCategory,
    RiskLevel,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _enum_column(enum_cls: type, **kwargs):
    """Non-native SQLAlchemy Enum (VARCHAR + CHECK constraint).

    Deliberately not a native PostgreSQL ENUM type: native enums require
    separate `CREATE TYPE`/`ALTER TYPE` migration steps whenever a value is
    added, which is friction the taxonomy/enum versioning story
    (Risk_Taxonomy_and_Labeling_Spec.md SS7) doesn't need this early, and it
    keeps the same model definitions portable across PostgreSQL (production)
    and SQLite (test), matching the `GUID` type's portability goal.
    """
    return SAEnum(enum_cls, native_enum=False, validate_strings=True, **kwargs)


class User(Base):
    """PROVISIONAL_V2 — see docs/PROVISIONAL_DECISIONS.md.

    Security_and_Privacy_v2.md SS4 says auth is "unchanged from the original
    Security and Access Document": no login required for core use,
    unguessable per-document access tokens, optional passwordless magic-link
    login for saved history (post-MVP). That original document is not
    available here, so this table is the smallest shape that supports the
    explicitly-stated future magic-link login without inventing a fuller
    auth system now.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    documents: Mapped[list[Document]] = relationship(back_populates="user")


class Document(Base):
    """`document_type` / `document_type_confidence` are explicit v2 additions
    (API_and_Data_Models.md SS2). All other columns are PROVISIONAL_V2 base
    fields (v1 shape unavailable) — kept minimal: identity, ownership,
    access control, and original-file pointer only.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # PROVISIONAL_V2: unguessable per-document access token. Security_and_Privacy_v2.md
    # SS4 requires this explicitly; the generation mechanism/length is not specified
    # anywhere available, so a high-entropy opaque string is used (see corpus/README
    # and PROVISIONAL_DECISIONS.md).
    access_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # PROVISIONAL_V2: original filename and object-storage pointer.
    # Security_and_Privacy_v2.md SS2 requires originals stored in object
    # storage separate from the database — this column holds a reference
    # only, never file bytes.
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 2 upload/parsing metadata — not part of API_and_Data_Models.md SS2's
    # explicit `documents` additions (only document_type/document_type_confidence
    # are listed there); added because Phase 2 requires persisting safe
    # upload-time metadata somewhere. Plain string, not a shared canonical enum
    # (same precedent as FinancialEntity.entity_type) — see PROVISIONAL_DECISIONS.md.
    file_format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # PDF only — DOCX has no native page concept (see PROVISIONAL_DECISIONS.md).
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document_type: Mapped[DocumentType] = mapped_column(
        _enum_column(DocumentType), nullable=False, default=DocumentType.UNKNOWN
    )
    document_type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="documents")
    clauses: Mapped[list[Clause]] = relationship(back_populates="document", cascade="all, delete-orphan")
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Clause(Base):
    """`clause_index`, `raw_text`, `section_heading` and position are the
    Segmentation Service outputs described in Technical_Architecture_v2.md
    SS3. `segmentation_confidence` / `low_confidence_flag` are the explicit
    v2 additions (API_and_Data_Models.md SS2). Position is represented as
    `start_char`/`end_char`/`page_number` — the architecture doc says
    "text + position" without specifying the field shape, so this is the
    smallest reasonable concrete representation, not a v1-gap.
    """

    __tablename__ = "clauses"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    clause_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    segmentation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_confidence_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    document: Mapped[Document] = relationship(back_populates="clauses")
    analyses: Mapped[list[ClauseAnalysisORM]] = relationship(
        back_populates="clause", cascade="all, delete-orphan"
    )


class ClauseAnalysisORM(Base):
    """Fully specified by API_and_Data_Models.md SS2 (`clause_analyses`) — no
    provisional fields in this table."""

    __tablename__ = "clause_analyses"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    clause_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clauses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    risk_category: Mapped[RiskCategory | None] = mapped_column(_enum_column(RiskCategory), nullable=True)
    risk_subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)
    taxonomy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_party: Mapped[str | None] = mapped_column(Text, nullable=True)

    risk_level: Mapped[RiskLevel] = mapped_column(_enum_column(RiskLevel), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(_enum_column(ConfidenceLevel), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abstain_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    clause: Mapped[Clause] = relationship(back_populates="analyses")
    financial_entities: Mapped[list[FinancialEntity]] = relationship(
        back_populates="clause_analysis",
        cascade="all, delete-orphan",
        foreign_keys="FinancialEntity.clause_analysis_id",
    )
    evidence_spans: Mapped[list[EvidenceSpan]] = relationship(
        back_populates="clause_analysis", cascade="all, delete-orphan"
    )
    matched_patterns: Mapped[list[MatchedPattern]] = relationship(
        back_populates="clause_analysis", cascade="all, delete-orphan"
    )


class EvidenceSpan(Base):
    """Fully specified by API_and_Data_Models.md SS2 (`evidence_spans`)."""

    __tablename__ = "evidence_spans"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    clause_analysis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clause_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    clause_analysis: Mapped[ClauseAnalysisORM] = relationship(back_populates="evidence_spans")
    financial_entities: Mapped[list[FinancialEntity]] = relationship(
        back_populates="evidence_span", foreign_keys="FinancialEntity.evidence_span_id"
    )


class FinancialEntity(Base):
    """Fully specified by API_and_Data_Models.md SS2 (`financial_entities`).

    `entity_type` is intentionally a plain string column, not a SQLAlchemy
    enum: API_and_Data_Models.md SS1 does not define a canonical enum class
    for it (only an inline value list — percentage/amount/fee/rate/time_period
    — in SS2's table notes and the ClauseAnalysis schema), so promoting it to
    a new named canonical enum here would be inventing taxonomy beyond what
    v2 explicitly defines.
    """

    __tablename__ = "financial_entities"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    clause_analysis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clause_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_span_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("evidence_spans.id", ondelete="SET NULL"), nullable=True
    )

    clause_analysis: Mapped[ClauseAnalysisORM] = relationship(
        back_populates="financial_entities", foreign_keys=[clause_analysis_id]
    )
    evidence_span: Mapped[EvidenceSpan | None] = relationship(
        back_populates="financial_entities", foreign_keys=[evidence_span_id]
    )


class CorpusPattern(Base):
    """`taxonomy_version`, `annotator_confidence`, `is_negative_example` are
    the explicit v2 additions (API_and_Data_Models.md SS2: "extended from
    v1"). The base pattern shape (text, category, source) is PROVISIONAL_V2
    — no v1 `corpus_patterns` definition is available. `source` values
    ("cuad" | "scraped_indian") are drawn directly from the example in
    `matched_patterns` (Risk_Taxonomy_and_Labeling_Spec.md SS6), not invented.
    """

    __tablename__ = "corpus_patterns"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    pattern_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_category: Mapped[RiskCategory | None] = mapped_column(_enum_column(RiskCategory), nullable=True)
    risk_subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    taxonomy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    annotator_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_negative_example: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # PROVISIONAL_V2: Dataset_and_Evaluation_Spec.md SS3 requires corpus
    # versioning ("every labeled batch is tagged corpus_v1, corpus_v1.1...")
    # and AI_Risk_Engine_Design.md SS2/SS7 requires every retrieval result to
    # carry a corpus version and reject mismatches — but API_and_Data_Models.md
    # SS2's `corpus_patterns` column list (extended from v1) never lists a
    # corpus_version column. Added here as the smallest schema extension that
    # makes the explicitly-required versioning check possible. See
    # docs/PROVISIONAL_DECISIONS.md "Phase 4: corpus_version column".
    corpus_version: Mapped[str] = mapped_column(String(32), nullable=False, default="corpus_v1")

    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)

    matched_patterns: Mapped[list[MatchedPattern]] = relationship(back_populates="corpus_pattern")


class MatchedPattern(Base):
    """Fully specified by API_and_Data_Models.md SS2 (`matched_patterns`)."""

    __tablename__ = "matched_patterns"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    clause_analysis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clause_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    corpus_pattern_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("corpus_patterns.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    lexical_score: Mapped[float] = mapped_column(Float, nullable=False)

    clause_analysis: Mapped[ClauseAnalysisORM] = relationship(back_populates="matched_patterns")
    corpus_pattern: Mapped[CorpusPattern] = relationship(back_populates="matched_patterns")


class ProcessingJob(Base):
    """PROVISIONAL_V2 — see docs/PROVISIONAL_DECISIONS.md.

    Referenced as an existing, "unchanged from v1" table
    (API_and_Data_Models.md SS2) that tracks per-document pipeline stage,
    backing `GET /documents/{id}/status` (API_and_Data_Models.md SS3). No v1
    definition is available, so this is the smallest shape that supports
    that endpoint's documented response shape (`stage`, `error`).
    """

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[ProcessingStage] = mapped_column(
        _enum_column(ProcessingStage), nullable=False, default=ProcessingStage.QUEUED
    )
    # Pre-approved error code + non-sensitive category only — never a raw
    # exception message or traceback (Security_and_Privacy_v2.md SS6).
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow, nullable=False)

    document: Mapped[Document] = relationship(back_populates="processing_jobs")
