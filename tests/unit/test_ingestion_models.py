from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
    IngestionStatus,
    SourceLocation,
    SourceSystem,
)

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
VALID_HASH = "a" * 64


def metadata_payload(
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "source": SourceLocation(
            system=SourceSystem.LOCAL,
            source_id="synthetic-local",
            uri="local:///synthetic/policy.pdf",
        ),
        "filename": "policy.pdf",
        "document_format": DocumentFormat.PDF,
        "media_type": "application/pdf",
        "size_bytes": 1024,
        "content_sha256": VALID_HASH,
        "created_at": NOW,
        "modified_at": NOW,
        "access_groups": (" engineering ", "security"),
    }
    payload.update(overrides)
    return payload


def make_metadata(
    **overrides: object,
) -> DocumentMetadata:
    return DocumentMetadata.model_validate(metadata_payload(**overrides))


def test_accepts_traceable_document_metadata() -> None:
    metadata = make_metadata()

    assert metadata.document_id == DOCUMENT_ID
    assert metadata.version_id == VERSION_ID
    assert metadata.source.system is SourceSystem.LOCAL
    assert metadata.source.source_id == "synthetic-local"
    assert metadata.source.uri == "local:///synthetic/policy.pdf"
    assert metadata.document_format is DocumentFormat.PDF
    assert metadata.status is IngestionStatus.DISCOVERED
    assert metadata.access_groups == (
        "engineering",
        "security",
    )


def test_accepts_complete_s3_location() -> None:
    source = SourceLocation(
        system=SourceSystem.S3,
        source_id="synthetic-s3",
        uri="s3://synthetic-documents/policy.pdf",
        bucket="synthetic-documents",
        object_key="policy.pdf",
    )

    assert source.system is SourceSystem.S3
    assert source.source_id == "synthetic-s3"
    assert source.bucket == "synthetic-documents"
    assert source.object_key == "policy.pdf"


@pytest.mark.parametrize(
    ("bucket", "object_key"),
    [
        (None, "policy.pdf"),
        ("synthetic-documents", None),
        (None, None),
    ],
)
def test_rejects_incomplete_s3_coordinates(
    bucket: str | None,
    object_key: str | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match="both bucket and object_key",
    ):
        SourceLocation(
            system=SourceSystem.S3,
            source_id="synthetic-s3",
            uri="s3://synthetic-documents/policy.pdf",
            bucket=bucket,
            object_key=object_key,
        )


@pytest.mark.parametrize(
    ("source_id", "uri"),
    [
        ("", "local:///policy.pdf"),
        ("synthetic-local", ""),
    ],
)
def test_rejects_blank_source_identity(
    source_id: str,
    uri: str,
) -> None:
    with pytest.raises(ValidationError):
        SourceLocation(
            system=SourceSystem.LOCAL,
            source_id=source_id,
            uri=uri,
        )


def test_rejects_invalid_content_hash() -> None:
    with pytest.raises(
        ValidationError,
        match="content_sha256",
    ):
        make_metadata(content_sha256="not-a-sha256")


def test_rejects_negative_document_size() -> None:
    with pytest.raises(
        ValidationError,
        match="size_bytes",
    ):
        make_metadata(size_bytes=-1)


def test_rejects_timezone_naive_timestamp() -> None:
    with pytest.raises(
        ValidationError,
        match="timezone information",
    ):
        make_metadata(
            created_at=datetime(2026, 1, 1, 12, 0),
        )


def test_rejects_modified_time_before_creation() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot be earlier",
    ):
        make_metadata(
            modified_at=NOW - timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    "groups",
    [
        (),
        ("",),
        ("engineering", "engineering"),
    ],
)
def test_rejects_invalid_access_groups(
    groups: tuple[str, ...],
) -> None:
    with pytest.raises(
        ValidationError,
        match="access_groups",
    ):
        make_metadata(access_groups=groups)


def test_failed_ingestion_requires_reason() -> None:
    with pytest.raises(
        ValidationError,
        match="requires failure_reason",
    ):
        make_metadata(status=IngestionStatus.FAILED)


def test_accepts_failed_ingestion_with_reason() -> None:
    metadata = make_metadata(
        status=IngestionStatus.FAILED,
        failure_reason="Synthetic parser failure",
    )

    assert metadata.status is IngestionStatus.FAILED
    assert metadata.failure_reason == "Synthetic parser failure"


def test_rejects_failure_reason_for_successful_state() -> None:
    with pytest.raises(
        ValidationError,
        match="only valid for failed",
    ):
        make_metadata(
            status=IngestionStatus.INGESTED,
            failure_reason="Unexpected reason",
        )


def test_rejects_unknown_metadata_fields() -> None:
    payload = metadata_payload(unexpected_field="not permitted")

    with pytest.raises(
        ValidationError,
        match="unexpected_field",
    ):
        DocumentMetadata.model_validate(payload)
