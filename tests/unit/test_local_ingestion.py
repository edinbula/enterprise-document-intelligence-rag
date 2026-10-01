from hashlib import sha256
from pathlib import Path

import pytest

from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
    calculate_sha256,
    discover_local_documents,
)
from enterprise_document_rag.ingestion.models import (
    DocumentFormat,
    SourceSystem,
)


def test_discovers_supported_documents_in_stable_order(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()

    (tmp_path / "zeta.PDF").write_bytes(b"pdf")
    (nested / "alpha.txt").write_text(
        "text",
        encoding="utf-8",
    )
    (nested / "table.csv").write_text(
        "id,value\n1,test\n",
        encoding="utf-8",
    )
    (tmp_path / "ignored.exe").write_bytes(b"ignored")

    discovered = discover_local_documents(tmp_path)
    relative_paths = tuple(path.relative_to(tmp_path).as_posix() for path in discovered)

    assert relative_paths == (
        "nested/alpha.txt",
        "nested/table.csv",
        "zeta.PDF",
    )


def test_rejects_missing_document_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="not a directory",
    ):
        discover_local_documents(tmp_path / "missing")


def test_calculates_sha256_from_file_content(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    content = b"synthetic policy content"
    document.write_bytes(content)

    assert calculate_sha256(document) == sha256(content).hexdigest()


def test_builds_stable_traceable_metadata(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.pdf"
    document.write_bytes(b"synthetic pdf")

    first = build_local_metadata(
        document,
        tmp_path,
        access_groups=(" engineering ", "security"),
    )
    second = build_local_metadata(
        document,
        tmp_path,
    )

    assert first.document_id == second.document_id
    assert first.version_id == second.version_id
    assert first.source.system is SourceSystem.LOCAL
    assert first.source.source_id == "local-default"
    assert first.source.uri == "local:///policy.pdf"
    assert first.document_format is DocumentFormat.PDF
    assert first.media_type == "application/pdf"
    assert first.size_bytes == len(b"synthetic pdf")
    assert first.access_groups == (
        "engineering",
        "security",
    )


def test_content_change_creates_new_version_identity(
    tmp_path: Path,
) -> None:
    document = tmp_path / "procedure.txt"
    document.write_text(
        "version one",
        encoding="utf-8",
    )
    first = build_local_metadata(document, tmp_path)

    document.write_text(
        "version two",
        encoding="utf-8",
    )
    second = build_local_metadata(document, tmp_path)

    assert first.document_id == second.document_id
    assert first.version_id != second.version_id
    assert first.content_sha256 != second.content_sha256


def test_rejects_document_outside_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    outside = tmp_path / "outside.txt"
    outside.write_text(
        "outside",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="outside the configured root",
    ):
        build_local_metadata(outside, root)


def test_rejects_unsupported_document_format(
    tmp_path: Path,
) -> None:
    document = tmp_path / "archive.zip"
    document.write_bytes(b"archive")

    with pytest.raises(
        ValueError,
        match="unsupported document format",
    ):
        build_local_metadata(document, tmp_path)


def test_rejects_non_file_document(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(
        ValueError,
        match="not a regular file",
    ):
        build_local_metadata(directory, tmp_path)


def test_source_id_prevents_identity_collisions_between_roots(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first_document = first_root / "policy.txt"
    second_document = second_root / "policy.txt"

    first_document.write_text(
        "same content",
        encoding="utf-8",
    )
    second_document.write_text(
        "same content",
        encoding="utf-8",
    )

    first = build_local_metadata(
        first_document,
        first_root,
        source_id="department-a",
    )
    second = build_local_metadata(
        second_document,
        second_root,
        source_id="department-b",
    )

    assert first.document_id != second.document_id
    assert first.source.source_id == "department-a"
    assert second.source.source_id == "department-b"
