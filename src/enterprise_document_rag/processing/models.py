"""Typed contracts for normalized document-processing output."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from enterprise_document_rag.ingestion.models import DocumentMetadata


def _normalize_attributes(
    attributes: dict[str, str],
    *,
    field_name: str,
) -> dict[str, str]:
    """Normalize attributes without silently collapsing duplicate keys."""
    normalized: dict[str, str] = {}

    for key, value in attributes.items():
        normalized_key = key.strip()
        normalized_value = value.strip()

        if not normalized_key or not normalized_value:
            raise ValueError(f"{field_name} must use non-empty keys and values")

        if normalized_key in normalized:
            raise ValueError(f"{field_name} must remain unique after normalization")

        normalized[normalized_key] = normalized_value

    return normalized


class SegmentKind(StrEnum):
    """Kinds of normalized content produced by document parsers."""

    TEXT = "text"
    TABLE_ROW = "table-row"
    OCR_TEXT = "ocr-text"


class SegmentLocation(BaseModel):
    """Optional location of a segment within its source document."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    page_number: int | None = Field(
        default=None,
        ge=1,
    )
    row_number: int | None = Field(
        default=None,
        ge=1,
    )
    section: str | None = Field(
        default=None,
        min_length=1,
    )


class NormalizedSegment(BaseModel):
    """One ordered and traceable unit of normalized document content."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    segment_id: UUID
    document_id: UUID
    version_id: UUID
    ordinal: int = Field(ge=0)
    kind: SegmentKind
    text: str = Field(min_length=1)
    location: SegmentLocation = Field(
        default_factory=SegmentLocation,
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
    )

    @field_validator(
        "text",
        mode="before",
    )
    @classmethod
    def reject_blank_text(
        cls,
        value: str,
    ) -> str:
        """Reject segments that contain only whitespace."""
        if not value.strip():
            raise ValueError("segment text must not be blank")
        return value

    @field_validator(
        "attributes",
        mode="before",
    )
    @classmethod
    def validate_attributes(
        cls,
        attributes: dict[str, str],
    ) -> dict[str, str]:
        """Require normalized, non-empty, and unique attributes."""
        return _normalize_attributes(
            attributes,
            field_name="segment attributes",
        )


class ProcessorIdentity(BaseModel):
    """Identity of the parser that produced normalized content."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ProcessedDocument(BaseModel):
    """Validated handoff from parsing to downstream transformation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    source: DocumentMetadata
    processor: ProcessorIdentity
    processed_at: datetime
    segments: tuple[NormalizedSegment, ...] = Field(
        min_length=1,
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
    )

    @field_validator("processed_at")
    @classmethod
    def require_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        """Reject ambiguous processing timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("processed_at must include timezone information")
        return value

    @field_validator(
        "attributes",
        mode="before",
    )
    @classmethod
    def validate_attributes(
        cls,
        attributes: dict[str, str],
    ) -> dict[str, str]:
        """Require normalized, non-empty, and unique attributes."""
        return _normalize_attributes(
            attributes,
            field_name="document attributes",
        )

    @model_validator(mode="after")
    def validate_segments(self) -> Self:
        """Require traceable, unique, and contiguous segment ordering."""
        if any(segment.document_id != self.source.document_id for segment in self.segments):
            raise ValueError("segments must match the source document_id")

        if any(segment.version_id != self.source.version_id for segment in self.segments):
            raise ValueError("segments must match the source version_id")

        segment_ids = tuple(segment.segment_id for segment in self.segments)
        if len(set(segment_ids)) != len(segment_ids):
            raise ValueError("segment IDs must be unique")

        ordinals = tuple(segment.ordinal for segment in self.segments)
        expected_ordinals = tuple(range(len(self.segments)))
        if ordinals != expected_ordinals:
            raise ValueError("segments must use contiguous ordinal ordering")

        return self

    @property
    def segment_count(self) -> int:
        """Return the number of normalized segments."""
        return len(self.segments)
