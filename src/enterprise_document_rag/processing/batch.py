"""Recoverable batch processing for local ingestion manifests."""

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Self
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from enterprise_document_rag.ingestion.manifest import (
    IngestionManifest,
)
from enterprise_document_rag.ingestion.models import (
    DocumentMetadata,
    SourceSystem,
)
from enterprise_document_rag.processing.models import (
    ProcessedDocument,
)
from enterprise_document_rag.processing.registry import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
)


class ProcessingFailure(BaseModel):
    """Recoverable failure produced while processing one document."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    document_id: UUID
    version_id: UUID
    source_uri: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProcessingBatch(BaseModel):
    """Validated result of processing one ingestion manifest."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    batch_id: UUID
    manifest_id: UUID
    generated_at: datetime
    documents: tuple[ProcessedDocument, ...] = ()
    failures: tuple[ProcessingFailure, ...] = ()
    ingestion_failure_count: int = Field(ge=0)

    @field_validator("generated_at")
    @classmethod
    def require_timezone(
        cls,
        value: datetime,
    ) -> datetime:
        """Reject ambiguous batch timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_contents(self) -> Self:
        """Require unique identities and stable source ordering."""
        document_versions = tuple(document.source.version_id for document in self.documents)
        if len(set(document_versions)) != len(document_versions):
            raise ValueError("processed document versions must be unique")

        failure_versions = tuple(failure.version_id for failure in self.failures)
        if len(set(failure_versions)) != len(failure_versions):
            raise ValueError("processing failure versions must be unique")

        if set(document_versions) & set(failure_versions):
            raise ValueError("document versions cannot both succeed and fail")

        document_uris = tuple(document.source.source.uri for document in self.documents)
        if document_uris != tuple(sorted(document_uris)):
            raise ValueError("processed documents must use stable URI ordering")

        failure_uris = tuple(failure.source_uri for failure in self.failures)
        if failure_uris != tuple(sorted(failure_uris)):
            raise ValueError("processing failures must use stable URI ordering")

        return self

    @property
    def document_count(self) -> int:
        """Return the number of successfully processed documents."""
        return len(self.documents)

    @property
    def failure_count(self) -> int:
        """Return the number of processing failures."""
        return len(self.failures)


def _resolve_local_document(
    root: Path,
    metadata: DocumentMetadata,
) -> Path:
    """Resolve one trusted local URI beneath the configured root."""
    if metadata.source.system is not SourceSystem.LOCAL:
        raise ValueError("local batch processing requires local source metadata")

    prefix = "local:///"
    if not metadata.source.uri.startswith(prefix):
        raise ValueError("local source URI must begin with local:///")

    relative_text = metadata.source.uri.removeprefix(prefix)
    relative_path = PurePosixPath(relative_text)

    if not relative_text or relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("local source URI contains an unsafe path")

    resolved_root = root.resolve()
    resolved_document = resolved_root.joinpath(*relative_path.parts).resolve()

    try:
        resolved_document.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("local source URI resolves outside the configured root") from error

    return resolved_document


def _build_batch_id(
    manifest: IngestionManifest,
    *,
    documents: tuple[ProcessedDocument, ...],
    failures: tuple[ProcessingFailure, ...],
) -> UUID:
    """Build stable identity from the manifest and processing outcome."""
    document_parts = (f"document:{document.source.version_id}" for document in documents)
    failure_parts = (
        (f"failure:{failure.version_id}:{failure.error_type}:{failure.message}")
        for failure in failures
    )
    identity = "|".join(
        (
            str(manifest.manifest_id),
            *document_parts,
            *failure_parts,
        )
    )
    return uuid5(
        manifest.manifest_id,
        identity,
    )


def process_local_manifest(
    root: Path,
    manifest: IngestionManifest,
    *,
    generated_at: datetime | None = None,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> ProcessingBatch:
    """Process every acquired local document without failing the batch."""
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"document root is not a directory: {root}")

    if manifest.source_system is not SourceSystem.LOCAL:
        raise ValueError("local batch processing requires a local manifest")

    batch_time = generated_at or datetime.now(UTC)
    documents: list[ProcessedDocument] = []
    failures: list[ProcessingFailure] = []

    for metadata in manifest.documents:
        try:
            path = _resolve_local_document(
                resolved_root,
                metadata,
            )
            processed = registry.parse(
                path,
                metadata,
                processed_at=batch_time,
            )
        except (OSError, ValueError) as error:
            failures.append(
                ProcessingFailure(
                    document_id=metadata.document_id,
                    version_id=metadata.version_id,
                    source_uri=metadata.source.uri,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
        else:
            documents.append(processed)

    ordered_documents = tuple(
        sorted(
            documents,
            key=lambda document: document.source.source.uri,
        )
    )
    ordered_failures = tuple(
        sorted(
            failures,
            key=lambda failure: failure.source_uri,
        )
    )

    return ProcessingBatch(
        batch_id=_build_batch_id(
            manifest,
            documents=ordered_documents,
            failures=ordered_failures,
        ),
        manifest_id=manifest.manifest_id,
        generated_at=batch_time,
        documents=ordered_documents,
        failures=ordered_failures,
        ingestion_failure_count=manifest.failure_count,
    )
