"""Typed ingestion manifests and deterministic local manifest generation."""

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
    discover_local_documents,
)
from enterprise_document_rag.ingestion.models import (
    DocumentMetadata,
    SourceSystem,
)


class IngestionFailure(BaseModel):
    """Recoverable failure recorded for one source document."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class IngestionManifest(BaseModel):
    """Deterministic handoff from acquisition to document processing."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    manifest_id: UUID
    source_id: str = Field(min_length=1)
    source_system: SourceSystem
    generated_at: datetime
    documents: tuple[DocumentMetadata, ...] = ()
    failures: tuple[IngestionFailure, ...] = ()

    @field_validator("generated_at")
    @classmethod
    def require_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        """Reject ambiguous manifest timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_contents(self) -> Self:
        """Require consistent source identity and deterministic ordering."""
        if any(document.source.source_id != self.source_id for document in self.documents):
            raise ValueError("manifest documents must match source_id")

        if any(document.source.system is not self.source_system for document in self.documents):
            raise ValueError("manifest documents must match source_system")

        if any(failure.source_id != self.source_id for failure in self.failures):
            raise ValueError("manifest failures must match source_id")

        version_ids = tuple(document.version_id for document in self.documents)
        if len(set(version_ids)) != len(version_ids):
            raise ValueError("manifest document versions must be unique")

        document_uris = tuple(document.source.uri for document in self.documents)
        if document_uris != tuple(sorted(document_uris)):
            raise ValueError("manifest documents must use stable URI ordering")

        failure_uris = tuple(failure.uri for failure in self.failures)
        if failure_uris != tuple(sorted(failure_uris)):
            raise ValueError("manifest failures must use stable URI ordering")

        return self

    @property
    def document_count(self) -> int:
        """Return the number of successfully acquired documents."""
        return len(self.documents)

    @property
    def failure_count(self) -> int:
        """Return the number of recoverable acquisition failures."""
        return len(self.failures)


def _build_manifest_id(
    *,
    source_id: str,
    documents: tuple[DocumentMetadata, ...],
    failures: tuple[IngestionFailure, ...],
) -> UUID:
    """Build stable identity from the complete manifest contents."""
    document_parts = (f"document:{document.version_id}" for document in documents)
    failure_parts = (
        (f"failure:{failure.uri}:{failure.error_type}:{failure.message}") for failure in failures
    )
    identity = "|".join(
        (
            source_id,
            *document_parts,
            *failure_parts,
        )
    )
    return uuid5(NAMESPACE_URL, identity)


def build_local_manifest(
    root: Path,
    *,
    source_id: str = "local-default",
    access_groups: Iterable[str] = ("public",),
    generated_at: datetime | None = None,
) -> IngestionManifest:
    """Discover local documents and record recoverable file failures."""
    documents: list[DocumentMetadata] = []
    failures: list[IngestionFailure] = []

    for path in discover_local_documents(root):
        relative_uri = f"local:///{path.relative_to(root.resolve()).as_posix()}"

        try:
            metadata = build_local_metadata(
                path,
                root,
                source_id=source_id,
                access_groups=access_groups,
            )
        except (OSError, ValueError) as error:
            failures.append(
                IngestionFailure(
                    source_id=source_id,
                    uri=relative_uri,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            documents.append(metadata)

    ordered_documents = tuple(
        sorted(
            documents,
            key=lambda document: document.source.uri,
        )
    )
    ordered_failures = tuple(
        sorted(
            failures,
            key=lambda failure: failure.uri,
        )
    )

    return IngestionManifest(
        manifest_id=_build_manifest_id(
            source_id=source_id,
            documents=ordered_documents,
            failures=ordered_failures,
        ),
        source_id=source_id,
        source_system=SourceSystem.LOCAL,
        generated_at=generated_at or datetime.now(UTC),
        documents=ordered_documents,
        failures=ordered_failures,
    )
