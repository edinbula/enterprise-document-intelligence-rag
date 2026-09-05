"""Typed contracts shared by every document-ingestion adapter."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentFormat(StrEnum):
    """Document formats supported by the ingestion boundary."""

    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"
    TXT = "txt"
    IMAGE = "image"


class SourceSystem(StrEnum):
    """Systems from which documents can be acquired."""

    LOCAL = "local"
    S3 = "s3"
    DATABRICKS_VOLUME = "databricks-volume"
    SHAREPOINT = "sharepoint"


class IngestionStatus(StrEnum):
    """Lifecycle states assigned by document acquisition."""

    DISCOVERED = "discovered"
    INGESTED = "ingested"
    FAILED = "failed"


class SourceLocation(BaseModel):
    """Stable location of a source document."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    system: SourceSystem
    uri: str = Field(min_length=1)
    bucket: str | None = None
    object_key: str | None = None

    @model_validator(mode="after")
    def validate_s3_coordinates(self) -> Self:
        """Require explicit bucket coordinates for S3 documents."""
        if self.system is SourceSystem.S3 and not (self.bucket and self.object_key):
            raise ValueError("S3 sources require both bucket and object_key")
        return self


class DocumentMetadata(BaseModel):
    """Traceable metadata recorded for every acquired document version."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    document_id: UUID
    version_id: UUID
    source: SourceLocation
    filename: str = Field(min_length=1)
    document_format: DocumentFormat
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    modified_at: datetime
    access_groups: tuple[str, ...] = ("public",)
    attributes: dict[str, str] = Field(default_factory=dict)
    status: IngestionStatus = IngestionStatus.DISCOVERED
    failure_reason: str | None = None

    @field_validator("created_at", "modified_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous timestamps without a UTC offset."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include timezone information")
        return value

    @field_validator("access_groups")
    @classmethod
    def validate_access_groups(cls, groups: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, non-empty authorization groups."""
        normalized = tuple(group.strip() for group in groups)
        if not normalized or any(not group for group in normalized):
            raise ValueError("access_groups must contain non-empty values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("access_groups must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        """Keep timestamps and failure information internally consistent."""
        if self.modified_at < self.created_at:
            raise ValueError("modified_at cannot be earlier than created_at")
        if self.status is IngestionStatus.FAILED and not self.failure_reason:
            raise ValueError("failed ingestion requires failure_reason")
        if self.status is not IngestionStatus.FAILED and self.failure_reason:
            raise ValueError("failure_reason is only valid for failed ingestion")
        return self
