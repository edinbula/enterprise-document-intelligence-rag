"""Deterministic paragraph and table extraction from DOCX documents."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid5
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph

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
    name="python-docx-parser",
    version="1.0",
)


def _build_paragraph_segment(
    source: DocumentMetadata,
    *,
    ordinal: int,
    paragraph_index: int,
    block_index: int,
    style: str,
    text: str,
) -> NormalizedSegment:
    """Build one stable segment from a normalized DOCX paragraph."""
    text_hash = sha256(text.encode("utf-8")).hexdigest()
    segment_id = uuid5(
        source.version_id,
        (f"docx-paragraph:{paragraph_index}:{text_hash}"),
    )

    attributes = {
        "block_index": str(block_index),
        "paragraph_index": str(paragraph_index),
    }
    if style:
        attributes["style"] = style

    return NormalizedSegment(
        segment_id=segment_id,
        document_id=source.document_id,
        version_id=source.version_id,
        ordinal=ordinal,
        kind=SegmentKind.TEXT,
        text=text,
        location=SegmentLocation(
            section=style or None,
        ),
        attributes=attributes,
    )


def _build_table_row_segment(
    source: DocumentMetadata,
    *,
    ordinal: int,
    table_index: int,
    row_index: int,
    block_index: int,
    cells: tuple[str, ...],
) -> NormalizedSegment:
    """Build one stable segment from a normalized DOCX table row."""
    text = " | ".join(cells)
    row_hash = sha256(text.encode("utf-8")).hexdigest()
    segment_id = uuid5(
        source.version_id,
        (f"docx-table:{table_index}:row:{row_index}:{row_hash}"),
    )

    return NormalizedSegment(
        segment_id=segment_id,
        document_id=source.document_id,
        version_id=source.version_id,
        ordinal=ordinal,
        kind=SegmentKind.TABLE_ROW,
        text=text,
        location=SegmentLocation(
            row_number=row_index,
        ),
        attributes={
            "block_index": str(block_index),
            "table_index": str(table_index),
            "row_index": str(row_index),
            "cell_count": str(len(cells)),
        },
    )


def parse_docx(
    path: Path,
    source: DocumentMetadata,
    *,
    processed_at: datetime | None = None,
) -> ProcessedDocument:
    """Extract ordered paragraphs and table rows from a verified DOCX."""
    resolved_path = path.resolve()

    if source.document_format is not DocumentFormat.DOCX:
        raise ValueError("DOCX parser requires DOCX document metadata")

    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError(f"document is not a regular file: {path}")

    if resolved_path.name != source.filename:
        raise ValueError("document filename does not match ingestion metadata")

    actual_hash = calculate_sha256(resolved_path)
    if actual_hash != source.content_sha256:
        raise ValueError("document content does not match ingestion metadata")

    try:
        document = Document(str(resolved_path))
    except (
        BadZipFile,
        KeyError,
        OSError,
        PackageNotFoundError,
        ValueError,
    ) as error:
        raise ValueError("DOCX document could not be read") from error

    segments: list[NormalizedSegment] = []
    paragraph_index = 0
    table_index = 0
    table_row_count = 0
    empty_block_count = 0

    for block_index, block in enumerate(
        document.iter_inner_content(),
        start=1,
    ):
        if isinstance(
            block,
            Paragraph,
        ):
            paragraph_index += 1
            text = normalize_plain_text(block.text)
            if not text:
                empty_block_count += 1
                continue

            style = block.style.name if block.style is not None else ""
            segments.append(
                _build_paragraph_segment(
                    source,
                    ordinal=len(segments),
                    paragraph_index=paragraph_index,
                    block_index=block_index,
                    style=style,
                    text=text,
                )
            )
            continue

        if isinstance(  # pragma: no branch
            block,
            Table,
        ):
            table_index += 1

            for row_index, row in enumerate(
                block.rows,
                start=1,
            ):
                cells = tuple(normalize_plain_text(cell.text) for cell in row.cells)
                if not any(cells):
                    empty_block_count += 1
                    continue

                table_row_count += 1
                segments.append(
                    _build_table_row_segment(
                        source,
                        ordinal=len(segments),
                        table_index=table_index,
                        row_index=row_index,
                        block_index=block_index,
                        cells=cells,
                    )
                )

    if not segments:
        raise ValueError("DOCX document contains no processable content")

    return ProcessedDocument(
        source=source,
        processor=_PROCESSOR,
        processed_at=processed_at or datetime.now(UTC),
        segments=tuple(segments),
        attributes={
            "paragraph_count": str(paragraph_index),
            "table_count": str(table_index),
            "table_row_count": str(table_row_count),
            "empty_block_count": str(empty_block_count),
            "normalization": "unicode-nfc",
        },
    )
