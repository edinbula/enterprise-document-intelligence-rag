"""Document-ingestion contracts and adapters."""

from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
    discover_local_documents,
)
from enterprise_document_rag.ingestion.manifest import (
    IngestionFailure,
    IngestionManifest,
    build_local_manifest,
)
from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
    IngestionStatus,
    SourceLocation,
    SourceSystem,
)
from enterprise_document_rag.ingestion.persistence import (
    read_manifest,
    write_manifest,
)

__all__ = [
    "DocumentFormat",
    "DocumentMetadata",
    "IngestionFailure",
    "IngestionManifest",
    "IngestionStatus",
    "SourceLocation",
    "SourceSystem",
    "build_local_manifest",
    "build_local_metadata",
    "discover_local_documents",
    "read_manifest",
    "write_manifest",
]
