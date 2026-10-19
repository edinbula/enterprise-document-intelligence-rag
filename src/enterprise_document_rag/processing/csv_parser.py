"""Deterministic processing for UTF-8 CSV documents."""

from csv import Error as CsvError
from csv import reader
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
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
    SegmentLocation,
)
from enterprise_document_rag.processing.text import (
    normalize_plain_text,
)

_PROCESSOR = ProcessorIdentity(
    name="csv-parser",
    version="1.0",
)


def _normalize_headers(
    headers: list[str],
) -> tuple[str, ...]:
    """Normalize and validate CSV column names."""
    normalized = tuple(normalize_plain_text(header) for header in headers)

    if not normalized or any(not header for header in normalized):
        raise ValueError("CSV header must contain non-empty column names")

    if len(set(normalized)) != len(normalized):
        raise ValueError("CSV column names must be unique after normalization")

    return normalized


def _read_csv_records(
    path: Path,
) -> tuple[
    tuple[str, ...],
    tuple[tuple[int, tuple[str, ...]], ...],
]:
    """Read normalized CSV records with logical record numbers."""
    records: list[tuple[int, tuple[str, ...]]] = []

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as source:
            csv_reader = reader(
                source,
                strict=True,
            )
            raw_headers = next(
                csv_reader,
                None,
            )

            if raw_headers is None:
                raise ValueError("CSV document must contain a header")

            headers = _normalize_headers(raw_headers)

            for record_number, raw_values in enumerate(
                csv_reader,
                start=2,
            ):
                if not raw_values or not any(value.strip() for value in raw_values):
                    continue

                if len(raw_values) != len(headers):
                    raise ValueError("CSV record column count does not match header")

                values = tuple(normalize_plain_text(value) for value in raw_values)
                records.append(
                    (
                        record_number,
                        values,
                    )
                )
    except UnicodeDecodeError as error:
        raise ValueError("CSV document must use UTF-8 encoding") from error
    except CsvError as error:
        raise ValueError("CSV document is malformed") from error

    if not records:
        raise ValueError("CSV document contains no processable records")

    return headers, tuple(records)


def _build_row_text(
    headers: tuple[str, ...],
    values: tuple[str, ...],
) -> str:
    """Build retrieval-friendly text from one CSV record."""
    return "\n".join(
        f"{header}: {value}"
        for header, value in zip(
            headers,
            values,
            strict=True,
        )
        if value
    )


def _build_row_segment(
    source: DocumentMetadata,
    *,
    headers: tuple[str, ...],
    record_number: int,
    values: tuple[str, ...],
    ordinal: int,
) -> NormalizedSegment:
    """Build one stable normalized segment from a CSV record."""
    text = _build_row_text(
        headers,
        values,
    )
    row_hash = sha256(text.encode("utf-8")).hexdigest()
    segment_id = uuid5(
        source.version_id,
        f"csv:{record_number}:{row_hash}",
    )

    return NormalizedSegment(
        segment_id=segment_id,
        document_id=source.document_id,
        version_id=source.version_id,
        ordinal=ordinal,
        kind=SegmentKind.TABLE_ROW,
        text=text,
        location=SegmentLocation(
            row_number=record_number,
        ),
        attributes={
            "column_count": str(len(headers)),
        },
    )


def parse_csv(
    path: Path,
    source: DocumentMetadata,
    *,
    processed_at: datetime | None = None,
) -> ProcessedDocument:
    """Parse a verified UTF-8 CSV document."""
    resolved_path = path.resolve()

    if source.document_format is not DocumentFormat.CSV:
        raise ValueError("CSV parser requires CSV document metadata")

    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError(f"document is not a regular file: {path}")

    if resolved_path.name != source.filename:
        raise ValueError("document filename does not match ingestion metadata")

    actual_hash = calculate_sha256(resolved_path)
    if actual_hash != source.content_sha256:
        raise ValueError("document content does not match ingestion metadata")

    headers, records = _read_csv_records(resolved_path)
    segments = tuple(
        _build_row_segment(
            source,
            headers=headers,
            record_number=record_number,
            values=values,
            ordinal=ordinal,
        )
        for ordinal, (
            record_number,
            values,
        ) in enumerate(records)
    )

    return ProcessedDocument(
        source=source,
        processor=_PROCESSOR,
        processed_at=processed_at or datetime.now(UTC),
        segments=segments,
        attributes={
            "encoding": "utf-8",
            "delimiter": ",",
            "column_count": str(len(headers)),
            "columns": "|".join(headers),
            "record_count": str(len(records)),
        },
    )
