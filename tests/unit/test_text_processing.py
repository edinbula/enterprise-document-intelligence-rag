from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
)
from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
)
from enterprise_document_rag.processing.models import (
    SegmentKind,
)
from enterprise_document_rag.processing.text import (
    normalize_plain_text,
    parse_plain_text,
)

PROCESSED_AT = datetime(
    2026,
    10,
    19,
    14,
    0,
    tzinfo=UTC,
)


def create_text_source(
    tmp_path: Path,
    *,
    filename: str = "policy.txt",
    content: str = "Synthetic policy.",
):
    document = tmp_path / filename
    document.write_text(
        content,
        encoding="utf-8",
        newline="",
    )
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
        access_groups=(
            "engineering",
            "security",
        ),
    )
    return document, metadata


def test_normalizes_unicode_line_endings_and_whitespace() -> None:
    raw_text = "\ufeffCafe\u0301 policy  \r\nSecond line\t \r\n\r\n\r\nFinal paragraph  \r\n"

    normalized = normalize_plain_text(raw_text)

    assert normalized == ("Café policy\nSecond line\n\nFinal paragraph")


def test_normalizes_empty_text() -> None:
    assert normalize_plain_text("\ufeff \r\n\t\r\n") == ""


def test_parses_plain_text_into_traceable_paragraphs(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(
        tmp_path,
        content=(
            "Access Control Policy\n"
            "Version 2.1\n"
            "\n"
            "Access must follow least privilege.\n"
            "Reviews occur quarterly.\n"
        ),
    )

    processed = parse_plain_text(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.source == metadata
    assert processed.processor.name == "plain-text-parser"
    assert processed.processor.version == "1.0"
    assert processed.processed_at == PROCESSED_AT
    assert processed.segment_count == 2
    assert processed.attributes == {
        "encoding": "utf-8",
        "normalization": "unicode-nfc",
    }

    first, second = processed.segments

    assert first.ordinal == 0
    assert first.kind is SegmentKind.TEXT
    assert first.text == ("Access Control Policy\nVersion 2.1")
    assert first.attributes == {
        "start_line": "1",
        "end_line": "2",
    }

    assert second.ordinal == 1
    assert second.text == ("Access must follow least privilege.\nReviews occur quarterly.")
    assert second.attributes == {
        "start_line": "4",
        "end_line": "5",
    }


def test_supports_utf8_byte_order_mark(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_bytes(b"\xef\xbb\xbfSynthetic policy.")
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )

    processed = parse_plain_text(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.segments[0].text == "Synthetic policy."


def test_generates_stable_segment_identities(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(
        tmp_path,
        content=("First paragraph.\n\nSecond paragraph.\n"),
    )

    first = parse_plain_text(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )
    second = parse_plain_text(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert tuple(segment.segment_id for segment in first.segments) == tuple(
        segment.segment_id for segment in second.segments
    )


def test_content_change_creates_new_segment_identity(
    tmp_path: Path,
) -> None:
    document, first_metadata = create_text_source(
        tmp_path,
        content="First version.",
    )
    first = parse_plain_text(
        document,
        first_metadata,
        processed_at=PROCESSED_AT,
    )

    document.write_text(
        "Second version.",
        encoding="utf-8",
    )
    second_metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )
    second = parse_plain_text(
        document,
        second_metadata,
        processed_at=PROCESSED_AT,
    )

    assert first.segments[0].segment_id != second.segments[0].segment_id


def test_uses_current_utc_time_by_default(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)

    processed = parse_plain_text(
        document,
        metadata,
    )

    assert processed.processed_at.tzinfo is not None
    assert processed.processed_at.utcoffset() is not None


def test_rejects_non_text_document_metadata(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)
    csv_metadata = metadata.model_copy(
        update={
            "document_format": DocumentFormat.CSV,
            "media_type": "text/csv",
        }
    )

    with pytest.raises(
        ValueError,
        match="requires TXT document metadata",
    ):
        parse_plain_text(
            document,
            csv_metadata,
        )


def test_rejects_missing_document(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)
    document.unlink()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_plain_text(
            document,
            metadata,
        )


def test_rejects_directory_as_document(
    tmp_path: Path,
) -> None:
    _document, metadata = create_text_source(tmp_path)
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_plain_text(
            directory,
            metadata,
        )


def test_rejects_symbolic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_text_source(tmp_path)
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: True,
    )

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_plain_text(
            document,
            metadata,
        )


def test_rejects_filename_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)
    mismatched = metadata.model_copy(
        update={
            "filename": "different.txt",
        }
    )

    with pytest.raises(
        ValueError,
        match="filename does not match",
    ):
        parse_plain_text(
            document,
            mismatched,
        )


def test_rejects_content_hash_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(
        tmp_path,
        content="Original content.",
    )
    document.write_text(
        "Changed content.",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="content does not match",
    ):
        parse_plain_text(
            document,
            metadata,
        )


def test_rejects_invalid_utf8(
    tmp_path: Path,
) -> None:
    document = tmp_path / "invalid.txt"
    document.write_bytes(b"\xff\xfe\xfa")
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )

    with pytest.raises(
        ValueError,
        match="must use UTF-8 encoding",
    ):
        parse_plain_text(
            document,
            metadata,
        )


def test_rejects_document_without_processable_content(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(
        tmp_path,
        content=" \n\t\n\n",
    )

    with pytest.raises(
        ValueError,
        match="no processable content",
    ):
        parse_plain_text(
            document,
            metadata,
        )


def test_segment_identity_is_a_uuid(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)

    processed = parse_plain_text(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert isinstance(
        processed.segments[0].segment_id,
        UUID,
    )
