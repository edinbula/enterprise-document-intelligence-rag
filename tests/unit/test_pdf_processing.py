from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest
from pypdf.errors import PdfReadError

import enterprise_document_rag.processing.pdf_parser as pdf_parser
from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
)
from enterprise_document_rag.ingestion.models import (
    DocumentMetadata,
)
from enterprise_document_rag.processing.models import (
    SegmentKind,
)
from enterprise_document_rag.processing.pdf_parser import (
    parse_pdf,
)

PROCESSED_AT = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


class FakePage:
    """Minimal PDF page with configurable extracted text."""

    def __init__(
        self,
        text: str | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._text = text
        self._error = error

    def extract_text(self) -> str | None:
        if self._error is not None:
            raise self._error
        return self._text


class FakeReader:
    """Minimal PDF reader used to isolate parser behavior."""

    def __init__(
        self,
        pages: list[FakePage],
        *,
        encrypted: bool = False,
    ) -> None:
        self.pages = pages
        self.is_encrypted = encrypted


def create_pdf_source(
    root: Path,
    *,
    filename: str = "policy.pdf",
    content: bytes = b"synthetic pdf content",
) -> tuple[Path, DocumentMetadata]:
    document = root / filename
    document.write_bytes(content)
    metadata = build_local_metadata(
        document,
        root,
        source_id="test-pdf-source",
    )
    return document, metadata


def install_fake_reader(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pages: list[FakePage],
    encrypted: bool = False,
) -> None:
    reader = FakeReader(
        pages,
        encrypted=encrypted,
    )

    def create_reader(
        path: Path,
        *,
        strict: bool,
    ) -> FakeReader:
        del path
        assert strict is True
        return reader

    monkeypatch.setattr(
        pdf_parser,
        "PdfReader",
        create_reader,
    )


def test_extracts_normalized_page_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[
            FakePage("\ufeffFirst page.\r\nSecond line.   "),
            FakePage("   \n\n"),
            FakePage("Cafe\u0301 policy."),
        ],
    )

    processed = parse_pdf(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.source == metadata
    assert processed.processor.name == "pypdf-parser"
    assert processed.processor.version == "1.0"
    assert processed.processed_at == PROCESSED_AT
    assert len(processed.segments) == 2

    first, second = processed.segments

    assert first.ordinal == 0
    assert first.kind is SegmentKind.TEXT
    assert first.text == "First page.\nSecond line."
    assert first.location.page_number == 1
    assert first.attributes == {"source": "embedded-pdf-text"}

    assert second.ordinal == 1
    assert second.text == "Café policy."
    assert second.location.page_number == 3

    assert processed.attributes == {
        "page_count": "3",
        "text_page_count": "2",
        "empty_page_count": "1",
        "normalization": "unicode-nfc",
    }


def test_builds_stable_page_segment_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[
            FakePage("Page one"),
            FakePage("Page two"),
        ],
    )

    first = parse_pdf(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )
    second = parse_pdf(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert tuple(segment.segment_id for segment in first.segments) == tuple(
        segment.segment_id for segment in second.segments
    )


def test_page_number_changes_segment_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[
            FakePage("Repeated text"),
            FakePage("Repeated text"),
        ],
    )

    processed = parse_pdf(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.segments[0].segment_id != processed.segments[1].segment_id


def test_uses_current_utc_time_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[
            FakePage("Extracted text"),
        ],
    )

    before = datetime.now(UTC)
    processed = parse_pdf(
        document,
        metadata,
    )
    after = datetime.now(UTC)

    assert before <= processed.processed_at <= after
    assert processed.processed_at.tzinfo is not None
    assert processed.processed_at.utcoffset() is not None


def test_rejects_non_pdf_metadata(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="test-source",
    )

    with pytest.raises(
        ValueError,
        match="requires PDF document metadata",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


def test_rejects_non_file_document(
    tmp_path: Path,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    document.unlink()
    document.mkdir()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


def test_rejects_symbolic_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)

    original_is_symlink = Path.is_symlink

    def is_symlink(
        path: Path,
    ) -> bool:
        if path == document:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(
        Path,
        "is_symlink",
        is_symlink,
    )

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


def test_rejects_filename_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    renamed = tmp_path / "renamed.pdf"
    renamed.write_bytes(document.read_bytes())

    with pytest.raises(
        ValueError,
        match="filename does not match",
    ):
        parse_pdf(
            renamed,
            metadata,
            processed_at=PROCESSED_AT,
        )


def test_rejects_content_hash_mismatch(
    tmp_path: Path,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    document.write_bytes(b"changed pdf content")

    with pytest.raises(
        ValueError,
        match="content does not match",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


@pytest.mark.parametrize(
    "error",
    [
        OSError("synthetic read failure"),
        PdfReadError("synthetic malformed PDF"),
    ],
)
def test_rejects_unreadable_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    document, metadata = create_pdf_source(tmp_path)

    def fail_reader(
        path: Path,
        *,
        strict: bool,
    ) -> NoReturn:
        del path
        del strict
        raise error

    monkeypatch.setattr(
        pdf_parser,
        "PdfReader",
        fail_reader,
    )

    with pytest.raises(
        ValueError,
        match="could not be read",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


def test_rejects_encrypted_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[],
        encrypted=True,
    )

    with pytest.raises(
        ValueError,
        match="encrypted PDF documents are not supported",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


@pytest.mark.parametrize(
    "error",
    [
        KeyError("synthetic key failure"),
        TypeError("synthetic type failure"),
        ValueError("synthetic value failure"),
    ],
)
def test_records_page_extraction_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=[
            FakePage(
                error=error,
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="text extraction failed on page 1",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [
            FakePage(None),
        ],
        [
            FakePage("   "),
            FakePage("\n\n"),
        ],
    ],
)
def test_requires_extractable_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pages: list[FakePage],
) -> None:
    document, metadata = create_pdf_source(tmp_path)
    install_fake_reader(
        monkeypatch,
        pages=pages,
    )

    with pytest.raises(
        ValueError,
        match="OCR is required",
    ):
        parse_pdf(
            document,
            metadata,
            processed_at=PROCESSED_AT,
        )
