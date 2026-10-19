from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
)
from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
)
from enterprise_document_rag.processing.csv_parser import (
    parse_csv,
)
from enterprise_document_rag.processing.models import (
    ProcessedDocument,
)
from enterprise_document_rag.processing.pdf_parser import (
    parse_pdf,
)
from enterprise_document_rag.processing.registry import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
    parse_document,
)
from enterprise_document_rag.processing.text import (
    parse_plain_text,
)

PROCESSED_AT = datetime(
    2026,
    10,
    19,
    16,
    0,
    tzinfo=UTC,
)


def create_text_source(
    tmp_path: Path,
) -> tuple[Path, DocumentMetadata]:
    document = tmp_path / "policy.txt"
    document.write_text(
        "Synthetic access-control policy.",
        encoding="utf-8",
    )
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )
    return document, metadata


def create_csv_source(
    tmp_path: Path,
) -> tuple[Path, DocumentMetadata]:
    document = tmp_path / "register.csv"
    document.write_text(
        "document_id,title\nPOL-001,Access Control Policy\n",
        encoding="utf-8",
    )
    metadata = build_local_metadata(
        document,
        tmp_path,
        source_id="synthetic-documents",
    )
    return document, metadata


class RecordingParser:
    def __init__(self) -> None:
        self.path: Path | None = None
        self.source: DocumentMetadata | None = None
        self.processed_at: datetime | None = None

    def __call__(
        self,
        path: Path,
        source: DocumentMetadata,
        *,
        processed_at: datetime | None = None,
    ) -> ProcessedDocument:
        self.path = path
        self.source = source
        self.processed_at = processed_at
        return parse_plain_text(
            path,
            source,
            processed_at=processed_at,
        )


def test_default_registry_exposes_stable_supported_formats() -> None:
    assert DEFAULT_PARSER_REGISTRY.supported_formats == (
        DocumentFormat.CSV,
        DocumentFormat.PDF,
        DocumentFormat.TXT,
    )


def test_returns_registered_parser() -> None:
    assert DEFAULT_PARSER_REGISTRY.get_parser(DocumentFormat.CSV) is parse_csv
    assert DEFAULT_PARSER_REGISTRY.get_parser(DocumentFormat.PDF) is parse_pdf
    assert DEFAULT_PARSER_REGISTRY.get_parser(DocumentFormat.TXT) is parse_plain_text


def test_routes_plain_text_through_default_registry(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)

    processed = parse_document(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.processor.name == "plain-text-parser"
    assert processed.processed_at == PROCESSED_AT
    assert processed.segments[0].text == "Synthetic access-control policy."


def test_routes_csv_through_default_registry(
    tmp_path: Path,
) -> None:
    document, metadata = create_csv_source(tmp_path)

    processed = parse_document(
        document,
        metadata,
        processed_at=PROCESSED_AT,
    )

    assert processed.processor.name == "csv-parser"
    assert processed.processed_at == PROCESSED_AT
    assert processed.segments[0].text == ("document_id: POL-001\ntitle: Access Control Policy")


def test_custom_registry_forwards_all_arguments(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)
    parser = RecordingParser()
    registry = ParserRegistry(
        {
            DocumentFormat.TXT: parser,
        }
    )

    processed = parse_document(
        document,
        metadata,
        processed_at=PROCESSED_AT,
        registry=registry,
    )

    assert parser.path == document
    assert parser.source == metadata
    assert parser.processed_at == PROCESSED_AT
    assert processed.processed_at == PROCESSED_AT


def test_registry_copies_the_input_mapping() -> None:
    parsers = {
        DocumentFormat.TXT: parse_plain_text,
    }
    registry = ParserRegistry(parsers)

    parsers[DocumentFormat.CSV] = parse_csv

    assert registry.supported_formats == (DocumentFormat.TXT,)


def test_supported_formats_use_lexical_order() -> None:
    registry = ParserRegistry(
        {
            DocumentFormat.TXT: parse_plain_text,
            DocumentFormat.PDF: parse_pdf,
            DocumentFormat.CSV: parse_csv,
        }
    )

    assert registry.supported_formats == (
        DocumentFormat.CSV,
        DocumentFormat.PDF,
        DocumentFormat.TXT,
    )


def test_rejects_empty_registry() -> None:
    with pytest.raises(
        ValueError,
        match="requires at least one parser",
    ):
        ParserRegistry({})


def test_rejects_unsupported_document_format(
    tmp_path: Path,
) -> None:
    document, metadata = create_text_source(tmp_path)
    unsupported = metadata.model_copy(
        update={
            "document_format": DocumentFormat.DOCX,
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="unsupported document format: docx",
    ):
        parse_document(
            document,
            unsupported,
        )
