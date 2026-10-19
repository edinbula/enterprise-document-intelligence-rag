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
from enterprise_document_rag.processing.csv_parser import (
    parse_csv,
)
from enterprise_document_rag.processing.models import (
    SegmentKind,
)

PROCESSED_AT = datetime(
    2026,
    10,
    19,
    15,
    0,
    tzinfo=UTC,
)


def create_csv_source(
    tmp_path: Path,
    *,
    filename: str = "register.csv",
    content: str = ("document_id,title,department\nPOL-001,Access Control Policy,Security\n"),
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


def test_parses_csv_into_traceable_row_segments(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=(
            "document_id,title,department\n"
            "POL-001,Access Control Policy,Security\n"
            'POL-002,"Data, Retention Policy",Governance\n'
        ),
    )

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.source == metadata
    assert processed.processor.name == "csv-parser"
    assert processed.processor.version == "1.0"
    assert processed.processed_at == PROCESSED_AT
    assert processed.segment_count == 2
    assert processed.attributes == {
        "encoding": "utf-8",
        "delimiter": ",",
        "column_count": "3",
        "columns": "document_id|title|department",
        "record_count": "2",
    }

    first, second = processed.segments

    assert first.ordinal == 0
    assert first.kind is SegmentKind.TABLE_ROW
    assert first.location.row_number == 2
    assert first.text == (
        "document_id: POL-001\ntitle: Access Control Policy\ndepartment: Security"
    )
    assert first.attributes == {
        "column_count": "3",
    }

    assert second.ordinal == 1
    assert second.location.row_number == 3
    assert second.text == (
        "document_id: POL-002\ntitle: Data, Retention Policy\ndepartment: Governance"
    )


def test_normalizes_headers_and_values(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=(" document_id , title \n POL-001 , Cafe\u0301 Policy \n"),
    )

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.attributes["columns"] == ("document_id|title")
    assert processed.segments[0].text == ("document_id: POL-001\ntitle: Café Policy")


def test_supports_utf8_byte_order_mark(
    tmp_path: Path,
) -> None:
    document = tmp_path / "register.csv"
    document.write_bytes(("\ufeffdocument_id,title\nPOL-001,Access Control\n").encode("utf-8"))
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.attributes["columns"] == ("document_id|title")


def test_omits_empty_values_from_retrieval_text(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id,title,department\nPOL-001,,Security\n"),
    )

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.segments[0].text == ("document_id: POL-001\ndepartment: Security")


def test_skips_blank_and_empty_records(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id,title,department\n\n,,\nPOL-001,Access Control,Security\n"),
    )

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.segment_count == 1
    assert processed.segments[0].location.row_number == 4


def test_generates_stable_segment_identities(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)

    first = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )
    second = parse_csv(
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
    document, first_metadata = create_csv_source(
        tmp_path,
        content=("document_id,title\nPOL-001,First Version\n"),
    )
    first = parse_csv(
        document,
        first_metadata,
        processed_at=PROCESSED_AT,
    )

    document.write_text(
        ("document_id,title\nPOL-001,Second Version\n"),
        encoding="utf-8",
    )
    second_metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )
    second = parse_csv(
        document,
        second_metadata,
        processed_at=PROCESSED_AT,
    )

    assert first.segments[0].segment_id != second.segments[0].segment_id


def test_uses_current_utc_time_by_default(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)

    processed = parse_csv(
        document,
        metadata,
    )

    assert processed.processed_at.tzinfo is not None
    assert processed.processed_at.utcoffset() is not None


def test_rejects_non_csv_document_metadata(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)
    text_metadata = metadata.model_copy(
        update={
            "document_format": DocumentFormat.TXT,
            "media_type": "text/plain",
        }
    )

    with pytest.raises(
        ValueError,
        match="requires CSV document metadata",
    ):
        parse_csv(
            document,
            text_metadata,
        )


def test_rejects_missing_document(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)
    document.unlink()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_directory_as_document(
    tmp_path: Path,
) -> None:
    _document, metadata = create_csv_source(tmp_path)
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_csv(
            directory,
            metadata,
        )


def test_rejects_symbolic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_csv_source(tmp_path)
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: True,
    )

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_filename_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)
    mismatched = metadata.model_copy(
        update={
            "filename": "different.csv",
        }
    )

    with pytest.raises(
        ValueError,
        match="filename does not match",
    ):
        parse_csv(
            document,
            mismatched,
        )


def test_rejects_content_hash_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)
    document.write_text(
        ("document_id,title\nPOL-999,Changed\n"),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="content does not match",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_empty_document(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content="",
    )

    with pytest.raises(
        ValueError,
        match="must contain a header",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_blank_first_record(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("\ndocument_id,title\nPOL-001,Policy\n"),
    )

    with pytest.raises(
        ValueError,
        match="non-empty column names",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_empty_header_name(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id,,department\nPOL-001,Policy,Security\n"),
    )

    with pytest.raises(
        ValueError,
        match="non-empty column names",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_duplicate_normalized_headers(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id, document_id \nPOL-001,POL-002\n"),
    )

    with pytest.raises(
        ValueError,
        match="must be unique after normalization",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_inconsistent_column_count(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id,title,department\nPOL-001,Policy\n"),
    )

    with pytest.raises(
        ValueError,
        match="column count does not match",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_header_without_records(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content="document_id,title\n",
    )

    with pytest.raises(
        ValueError,
        match="no processable records",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_only_empty_records(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=("document_id,title\n,\n,\n"),
    )

    with pytest.raises(
        ValueError,
        match="no processable records",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_rejects_invalid_utf8(
    tmp_path: Path,
) -> None:
    document = tmp_path / "invalid.csv"
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
        parse_csv(
            document,
            metadata,
        )


def test_rejects_malformed_csv(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(
        tmp_path,
        content=('document_id,title\nPOL-001,"Unclosed value\n'),
    )

    with pytest.raises(
        ValueError,
        match="CSV document is malformed",
    ):
        parse_csv(
            document,
            metadata,
        )


def test_segment_identity_is_a_uuid(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)

    processed = parse_csv(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert isinstance(
        processed.segments[0].segment_id,
        UUID,
    )
