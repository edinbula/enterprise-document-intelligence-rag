"""Typed parser registration and document-format routing."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

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
from enterprise_document_rag.processing.text import (
    parse_plain_text,
)


class DocumentParser(Protocol):
    """Callable contract implemented by document parsers."""

    def __call__(
        self,
        path: Path,
        source: DocumentMetadata,
        *,
        processed_at: datetime | None = None,
    ) -> ProcessedDocument:
        """Parse one verified source document."""


class ParserRegistry:
    """Immutable-by-interface mapping from formats to parsers."""

    __slots__ = ("_parsers",)

    def __init__(
        self,
        parsers: Mapping[
            DocumentFormat,
            DocumentParser,
        ],
    ) -> None:
        if not parsers:
            raise ValueError("parser registry requires at least one parser")

        self._parsers = dict(parsers)

    @property
    def supported_formats(
        self,
    ) -> tuple[DocumentFormat, ...]:
        """Return registered formats in stable lexical order."""
        return tuple(
            sorted(
                self._parsers,
                key=lambda document_format: document_format.value,
            )
        )

    def get_parser(
        self,
        document_format: DocumentFormat,
    ) -> DocumentParser:
        """Return the parser registered for a document format."""
        try:
            return self._parsers[document_format]
        except KeyError as error:
            raise ValueError(f"unsupported document format: {document_format.value}") from error

    def parse(
        self,
        path: Path,
        source: DocumentMetadata,
        *,
        processed_at: datetime | None = None,
    ) -> ProcessedDocument:
        """Route one document to its registered parser."""
        parser = self.get_parser(source.document_format)
        return parser(
            path,
            source,
            processed_at=processed_at,
        )


DEFAULT_PARSER_REGISTRY = ParserRegistry(
    {
        DocumentFormat.CSV: parse_csv,
        DocumentFormat.TXT: parse_plain_text,
    }
)


def parse_document(
    path: Path,
    source: DocumentMetadata,
    *,
    processed_at: datetime | None = None,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> ProcessedDocument:
    """Parse a document through the configured parser registry."""
    return registry.parse(
        path,
        source,
        processed_at=processed_at,
    )
