"""Normalized document-processing contracts and parsers."""

from enterprise_document_rag.processing.batch import (
    ProcessingBatch,
    ProcessingFailure,
    process_local_manifest,
)
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
from enterprise_document_rag.processing.pdf_parser import (
    parse_pdf,
)
from enterprise_document_rag.processing.persistence import (
    read_processing_batch,
    write_processing_batch,
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
    "ParserRegistry",
    "ProcessedDocument",
    "ProcessingBatch",
    "ProcessingFailure",
    "ProcessorIdentity",
    "SegmentKind",
    "SegmentLocation",
    "normalize_plain_text",
    "parse_csv",
    "parse_document",
    "parse_pdf",
    "parse_plain_text",
    "process_local_manifest",
    "read_processing_batch",
    "write_processing_batch",
]
