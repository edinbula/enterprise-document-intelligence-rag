"""Deterministic text extraction from verified PDF documents."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid5

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from enterprise_document_rag.ingestion.local import (
    calculate_sha256,
)
from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
)
from enterprise_document_rag.processing.models import (
    NormalizedSegment,
    ProcessedDocument,
    ProcessorIdentity,
    SegmentKind,
    SegmentLocation,
)
from enterprise_document_rag.processing.text import (
    normalize_plain_text,
)

_PROCESSOR = ProcessorIdentity(
    name="pypdf-parser",
    version="1.0",
)


def _build_page_segment(
    source: DocumentMetadata,
    *,
    ordinal: int,
    page_number: int,
    text: str,
) -> NormalizedSegment:
    """Build one stable normalized segment for an extracted PDF page."""
    page_hash = sha256(text.encode("utf-8")).hexdigest()
    segment_id = uuid5(
        source.version_id,
        (f"pdf-page:{page_number}:{page_hash}"),
    )

    return NormalizedSegment(
        segment_id=segment_id,
        document_id=source.document_id,
        version_id=source.version_id,
        ordinal=ordinal,
        kind=SegmentKind.TEXT,
        text=text,
        location=SegmentLocation(
            page_number=page_number,
        ),
        attributes={
            "source": "embedded-pdf-text",
        },
    )


def parse_pdf(
    path: Path,
    source: DocumentMetadata,
    *,
    processed_at: datetime | None = None,
) -> ProcessedDocument:
    """Extract normalized embedded text from a verified PDF document."""
    resolved_path = path.resolve()

    if source.document_format is not DocumentFormat.PDF:
        raise ValueError("PDF parser requires PDF document metadata")

    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError(f"document is not a regular file: {path}")

    if resolved_path.name != source.filename:
        raise ValueError("document filename does not match ingestion metadata")

    actual_hash = calculate_sha256(resolved_path)
    if actual_hash != source.content_sha256:
        raise ValueError("document content does not match ingestion metadata")

    try:
        reader = PdfReader(
            resolved_path,
            strict=True,
        )
    except (OSError, PdfReadError) as error:
        raise ValueError("PDF document could not be read") from error

    if reader.is_encrypted:
        raise ValueError("encrypted PDF documents are not supported")

    segments: list[NormalizedSegment] = []
    empty_page_count = 0
    page_count = len(reader.pages)

    for page_number, page in enumerate(
        reader.pages,
        start=1,
    ):
        try:
            extracted_text = page.extract_text() or ""
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"PDF text extraction failed on page {page_number}") from error

        normalized_text = normalize_plain_text(extracted_text)
        if not normalized_text:
            empty_page_count += 1
            continue

        segments.append(
            _build_page_segment(
                source,
                ordinal=len(segments),
                page_number=page_number,
                text=normalized_text,
            )
        )

    if not segments:
        raise ValueError("PDF document contains no extractable text; OCR is required")

    return ProcessedDocument(
        source=source,
        processor=_PROCESSOR,
        processed_at=processed_at or datetime.now(UTC),
        segments=tuple(segments),
        attributes={
            "page_count": str(page_count),
            "text_page_count": str(len(segments)),
            "empty_page_count": str(empty_page_count),
            "normalization": "unicode-nfc",
        },
    )
