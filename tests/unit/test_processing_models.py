from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
    SourceLocation,
    SourceSystem,
)
from enterprise_document_rag.processing.models import (
    NormalizedSegment,
    ProcessedDocument,
    ProcessorIdentity,
    SegmentKind,
    SegmentLocation,
)

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
SEGMENT_ID = UUID("33333333-3333-3333-3333-333333333333")
SECOND_SEGMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
PROCESSED_AT = datetime(
    2026,
    10,
    19,
    12,
    0,
    tzinfo=UTC,
)


def make_source() -> DocumentMetadata:
    return DocumentMetadata(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        source=SourceLocation(
            system=SourceSystem.LOCAL,
            source_id="synthetic-documents",
            uri="local:///policies/access-control-policy.txt",
        ),
        filename="access-control-policy.txt",
        document_format=DocumentFormat.TXT,
        media_type="text/plain",
        size_bytes=128,
        content_sha256="a" * 64,
        created_at=PROCESSED_AT,
        modified_at=PROCESSED_AT,
        access_groups=(
            "engineering",
            "security",
        ),
    )


def make_segment(
    *,
    segment_id: UUID = SEGMENT_ID,
    document_id: UUID = DOCUMENT_ID,
    version_id: UUID = VERSION_ID,
    ordinal: int = 0,
) -> NormalizedSegment:
    return NormalizedSegment(
        segment_id=segment_id,
        document_id=document_id,
        version_id=version_id,
        ordinal=ordinal,
        kind=SegmentKind.TEXT,
        text="Synthetic access-control policy.",
        location=SegmentLocation(
            page_number=1,
            section="Access Control",
        ),
        attributes={
            "classification": "internal",
        },
    )


def make_processed_document(
    *,
    segments: tuple[NormalizedSegment, ...] | None = None,
    processed_at: datetime = PROCESSED_AT,
    attributes: dict[str, str] | None = None,
) -> ProcessedDocument:
    return ProcessedDocument(
        source=make_source(),
        processor=ProcessorIdentity(
            name="plain-text-parser",
            version="1.0",
        ),
        processed_at=processed_at,
        segments=segments or (make_segment(),),
        attributes=attributes or {},
    )


def test_builds_valid_processed_document() -> None:
    processed = make_processed_document()

    assert processed.source.document_id == DOCUMENT_ID
    assert processed.processor.name == "plain-text-parser"
    assert processed.segments[0].kind is SegmentKind.TEXT
    assert processed.segments[0].location.page_number == 1
    assert processed.segment_count == 1


def test_segment_location_defaults_to_unknown() -> None:
    segment = NormalizedSegment(
        segment_id=SEGMENT_ID,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        ordinal=0,
        kind=SegmentKind.TEXT,
        text="Synthetic content.",
    )

    assert segment.location == SegmentLocation()


def test_normalizes_segment_attributes() -> None:
    segment = make_segment().model_copy(
        update={
            "attributes": {
                " department ": " engineering ",
            }
        }
    )
    validated = NormalizedSegment.model_validate(segment.model_dump())

    assert validated.attributes == {
        "department": "engineering",
    }


def test_rejects_blank_segment_text() -> None:
    with pytest.raises(
        ValidationError,
        match="segment text must not be blank",
    ):
        NormalizedSegment(
            segment_id=SEGMENT_ID,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            ordinal=0,
            kind=SegmentKind.TEXT,
            text="   ",
        )


def test_rejects_empty_segment_attribute_value() -> None:
    with pytest.raises(
        ValidationError,
        match="non-empty keys and values",
    ):
        NormalizedSegment(
            segment_id=SEGMENT_ID,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            ordinal=0,
            kind=SegmentKind.TEXT,
            text="Synthetic content.",
            attributes={
                "classification": "   ",
            },
        )


def test_rejects_segment_attributes_that_collide_after_normalization() -> None:
    with pytest.raises(
        ValidationError,
        match="remain unique after normalization",
    ):
        NormalizedSegment(
            segment_id=SEGMENT_ID,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            ordinal=0,
            kind=SegmentKind.TEXT,
            text="Synthetic content.",
            attributes={
                "department": "engineering",
                " department ": "security",
            },
        )


def test_rejects_invalid_segment_location() -> None:
    with pytest.raises(ValidationError):
        SegmentLocation(
            page_number=0,
        )


def test_rejects_unexpected_location_fields() -> None:
    with pytest.raises(ValidationError):
        SegmentLocation.model_validate(
            {
                "page_number": 1,
                "unknown": "value",
            }
        )


def test_rejects_naive_processing_timestamp() -> None:
    with pytest.raises(
        ValidationError,
        match="processed_at must include timezone information",
    ):
        make_processed_document(
            processed_at=datetime(
                2026,
                10,
                19,
                12,
                0,
            )
        )


def test_rejects_empty_segment_collection() -> None:
    with pytest.raises(ValidationError):
        ProcessedDocument(
            source=make_source(),
            processor=ProcessorIdentity(
                name="plain-text-parser",
                version="1.0",
            ),
            processed_at=PROCESSED_AT,
            segments=(),
        )


def test_rejects_mismatched_document_identity() -> None:
    invalid_segment = make_segment(document_id=UUID("55555555-5555-5555-5555-555555555555"))

    with pytest.raises(
        ValidationError,
        match="source document_id",
    ):
        make_processed_document(segments=(invalid_segment,))


def test_rejects_mismatched_version_identity() -> None:
    invalid_segment = make_segment(version_id=UUID("66666666-6666-6666-6666-666666666666"))

    with pytest.raises(
        ValidationError,
        match="source version_id",
    ):
        make_processed_document(segments=(invalid_segment,))


def test_rejects_duplicate_segment_identities() -> None:
    first = make_segment(
        ordinal=0,
    )
    second = make_segment(
        ordinal=1,
    )

    with pytest.raises(
        ValidationError,
        match="segment IDs must be unique",
    ):
        make_processed_document(
            segments=(
                first,
                second,
            )
        )


def test_rejects_non_contiguous_segment_ordering() -> None:
    first = make_segment(
        ordinal=0,
    )
    second = make_segment(
        segment_id=SECOND_SEGMENT_ID,
        ordinal=2,
    )

    with pytest.raises(
        ValidationError,
        match="contiguous ordinal ordering",
    ):
        make_processed_document(
            segments=(
                first,
                second,
            )
        )


def test_accepts_multiple_contiguously_ordered_segments() -> None:
    first = make_segment(
        ordinal=0,
    )
    second = make_segment(
        segment_id=SECOND_SEGMENT_ID,
        ordinal=1,
    )

    processed = make_processed_document(
        segments=(
            first,
            second,
        )
    )

    assert processed.segment_count == 2


def test_normalizes_document_attributes() -> None:
    processed = make_processed_document(
        attributes={
            " language ": " en ",
        }
    )

    assert processed.attributes == {
        "language": "en",
    }


def test_rejects_empty_document_attribute_key() -> None:
    with pytest.raises(
        ValidationError,
        match="non-empty keys and values",
    ):
        make_processed_document(
            attributes={
                "   ": "value",
            }
        )


def test_rejects_document_attributes_that_collide_after_normalization() -> None:
    with pytest.raises(
        ValidationError,
        match="remain unique after normalization",
    ):
        make_processed_document(
            attributes={
                "language": "en",
                " language ": "de",
            }
        )


def test_models_are_immutable() -> None:
    processed = make_processed_document()

    with pytest.raises(ValidationError):
        processed.processor.name = "changed"
