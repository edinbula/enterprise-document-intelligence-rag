"""Normalized document-processing contracts and parsers."""

from enterprise_document_rag.processing.csv_parser import (
    parse_csv,
)
from enterprise_document_rag.processing.models import (
    NormalizedSegment,
    ProcessedDocument,
    ProcessorIdentity,
    SegmentKind,
    SegmentLocation,
)
from enterprise_document_rag.processing.registry import (
    DEFAULT_PARSER_REGISTRY,
    DocumentParser,
    ParserRegistry,
    parse_document,
)
from enterprise_document_rag.processing.text import (
    normalize_plain_text,
    parse_plain_text,
)

__all__ = [
    "DEFAULT_PARSER_REGISTRY",
    "DocumentParser",
    "NormalizedSegment",
    "ParsedDocument",
    "ParserRegistry",
    "ProcessedDocument",
    "ProcessorIdentity",
    "SegmentKind",
    "SegmentLocation",
    "normalize_plain_text",
    "parse_csv",
    "parse_document",
    "parse_plain_text",
]
