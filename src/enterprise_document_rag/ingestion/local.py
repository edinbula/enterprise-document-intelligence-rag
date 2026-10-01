"""Deterministic local document discovery and metadata generation."""

from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    DocumentMetadata,
    SourceLocation,
    SourceSystem,
)

_FORMATS: dict[str, tuple[DocumentFormat, str]] = {
    ".csv": (DocumentFormat.CSV, "text/csv"),
    ".docx": (
        DocumentFormat.DOCX,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".jpeg": (DocumentFormat.IMAGE, "image/jpeg"),
    ".jpg": (DocumentFormat.IMAGE, "image/jpeg"),
    ".pdf": (DocumentFormat.PDF, "application/pdf"),
    ".png": (DocumentFormat.IMAGE, "image/png"),
    ".txt": (DocumentFormat.TXT, "text/plain"),
}

_HASH_CHUNK_SIZE = 1024 * 1024


def discover_local_documents(root: Path) -> tuple[Path, ...]:
    """Return supported regular files beneath an existing directory."""
    resolved_root = root.resolve()

    if not resolved_root.is_dir():
        raise ValueError(f"document root is not a directory: {root}")

    documents = (
        path
        for path in resolved_root.rglob("*")
        if (path.is_file() and not path.is_symlink() and path.suffix.lower() in _FORMATS)
    )

    return tuple(
        sorted(
            documents,
            key=lambda path: path.relative_to(resolved_root).as_posix(),
        )
    )


def calculate_sha256(path: Path) -> str:
    """Calculate a document hash without loading the complete file."""
    digest = sha256()

    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)

    return digest.hexdigest()


def build_local_metadata(
    path: Path,
    root: Path,
    *,
    source_id: str = "local-default",
    access_groups: Iterable[str] = ("public",),
) -> DocumentMetadata:
    """Build stable metadata for one discovered document version."""
    resolved_root = root.resolve()
    resolved_path = path.resolve()

    if path.is_symlink() or not resolved_path.is_file():
        raise ValueError(f"document is not a regular file: {path}")

    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"document is outside the configured root: {path}") from error

    try:
        document_format, media_type = _FORMATS[resolved_path.suffix.lower()]
    except KeyError as error:
        raise ValueError(f"unsupported document format: {path.suffix}") from error

    content_hash = calculate_sha256(resolved_path)
    relative_uri = f"local:///{relative_path.as_posix()}"

    document_identity = f"{SourceSystem.LOCAL.value}:{source_id}:{relative_path.as_posix()}"
    document_id = uuid5(NAMESPACE_URL, document_identity)
    version_id = uuid5(document_id, content_hash)

    file_status = resolved_path.stat()
    modified_at = datetime.fromtimestamp(
        file_status.st_mtime,
        tz=UTC,
    )

    return DocumentMetadata(
        document_id=document_id,
        version_id=version_id,
        source=SourceLocation(
            system=SourceSystem.LOCAL,
            source_id=source_id,
            uri=relative_uri,
        ),
        filename=resolved_path.name,
        document_format=document_format,
        media_type=media_type,
        size_bytes=file_status.st_size,
        content_sha256=content_hash,
        created_at=modified_at,
        modified_at=modified_at,
        access_groups=tuple(access_groups),
    )
