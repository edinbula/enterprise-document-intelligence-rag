"""Deterministic parsing and normalization for plain-text documents."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from unicodedata import normalize
from uuid import uuid5

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
)

_PROCESSOR = ProcessorIdentity(
    name="plain-text-parser",
    version="1.0",
)


def normalize_plain_text(text: str) -> str:
    """Normalize plain text without changing its semantic structure."""
    without_bom = text.lstrip("\ufeff")
    canonical = normalize(
        "NFC",
        without_bom,
    )
    unix_lines = canonical.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )
    trimmed_lines = (line.rstrip() for line in unix_lines.split("\n"))
    trimmed = "\n".join(trimmed_lines).strip()
    return sub(
        r"\n{3,}",
        "\n\n",
        trimmed,
    )


def _extract_paragraphs(
    text: str,
) -> tuple[tuple[str, int, int], ...]:
    """Return paragraphs with inclusive normalized line ranges."""
    paragraphs: list[tuple[str, int, int]] = []
    start_line = 1

    for paragraph in text.split("\n\n"):
        line_count = paragraph.count("\n") + 1
        end_line = start_line + line_count - 1
        paragraphs.append(
            (
                paragraph,
                start_line,
                end_line,
            )
        )
        start_line = end_line + 2

    return tuple(paragraphs)


def _build_segment(
    source: DocumentMetadata,
    *,
    ordinal: int,
    text: str,
    start_line: int,
    end_line: int,
) -> NormalizedSegment:
    """Build one stable segment from normalized paragraph content."""
    paragraph_hash = sha256(text.encode("utf-8")).hexdigest()
    segment_id = uuid5(
        source.version_id,
        f"text:{ordinal}:{paragraph_hash}",
    )

    return NormalizedSegment(
        segment_id=segment_id,
        document_id=source.document_id,
        version_id=source.version_id,
        ordinal=ordinal,
        kind=SegmentKind.TEXT,
        text=text,
        attributes={
            "start_line": str(start_line),
            "end_line": str(end_line),
        },
    )


def parse_plain_text(
    path: Path,
    source: DocumentMetadata,
    *,
    processed_at: datetime | None = None,
) -> ProcessedDocument:
    """Parse a verified UTF-8 plain-text document."""
    resolved_path = path.resolve()

    if source.document_format is not DocumentFormat.TXT:
        raise ValueError("plain-text parser requires TXT document metadata")

    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError(f"document is not a regular file: {path}")

    if resolved_path.name != source.filename:
        raise ValueError("document filename does not match ingestion metadata")

    actual_hash = calculate_sha256(resolved_path)
    if actual_hash != source.content_sha256:
        raise ValueError("document content does not match ingestion metadata")

    try:
        raw_text = resolved_path.read_text(
            encoding="utf-8-sig",
        )
    except UnicodeDecodeError as error:
        raise ValueError("plain-text document must use UTF-8 encoding") from error

    normalized_text = normalize_plain_text(raw_text)
    if not normalized_text:
        raise ValueError("plain-text document contains no processable content")

    paragraphs = _extract_paragraphs(normalized_text)
    segments = tuple(
        _build_segment(
            source,
            ordinal=ordinal,
            text=paragraph,
            start_line=start_line,
            end_line=end_line,
        )
        for ordinal, (
            paragraph,
            start_line,
            end_line,
        ) in enumerate(paragraphs)
    )

    return ProcessedDocument(
        source=source,
        processor=_PROCESSOR,
        processed_at=processed_at or datetime.now(UTC),
        segments=segments,
        attributes={
            "encoding": "utf-8",
            "normalization": "unicode-nfc",
        },
    )
