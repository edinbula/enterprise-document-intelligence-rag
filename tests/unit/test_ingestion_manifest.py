from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

import enterprise_document_rag.ingestion.manifest as manifest_module
from enterprise_document_rag.ingestion.local import (
    build_local_metadata,
)
from enterprise_document_rag.ingestion.manifest import (
    IngestionFailure,
    IngestionManifest,
    build_local_manifest,
)
from enterprise_document_rag.ingestion.models import (
    DocumentMetadata,
    SourceSystem,
)

MANIFEST_ID = UUID("33333333-3333-3333-3333-333333333333")
GENERATED_AT = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


def create_document(
    root: Path,
    filename: str,
    content: str,
) -> Path:
    document = root / filename
    document.write_text(
        content,
        encoding="utf-8",
    )
    return document


def make_metadata(
    root: Path,
    filename: str,
    *,
    source_id: str = "test-source",
) -> DocumentMetadata:
    document = create_document(
        root,
        filename,
        filename,
    )
    return build_local_metadata(
        document,
        root,
        source_id=source_id,
    )


def make_manifest(
    *,
    documents: tuple[DocumentMetadata, ...] = (),
    failures: tuple[IngestionFailure, ...] = (),
    source_id: str = "test-source",
    source_system: SourceSystem = SourceSystem.LOCAL,
    generated_at: datetime = GENERATED_AT,
) -> IngestionManifest:
    return IngestionManifest(
        manifest_id=MANIFEST_ID,
        source_id=source_id,
        source_system=source_system,
        generated_at=generated_at,
        documents=documents,
        failures=failures,
    )


def test_builds_deterministic_local_manifest(
    tmp_path: Path,
) -> None:
    create_document(
        tmp_path,
        "zeta.txt",
        "zeta",
    )
    create_document(
        tmp_path,
        "alpha.txt",
        "alpha",
    )

    first = build_local_manifest(
        tmp_path,
        source_id="policies",
        access_groups=("engineering",),
        generated_at=GENERATED_AT,
    )
    second = build_local_manifest(
        tmp_path,
        source_id="policies",
        access_groups=("engineering",),
        generated_at=GENERATED_AT,
    )

    assert first.manifest_id == second.manifest_id
    assert first.source_id == "policies"
    assert first.source_system is SourceSystem.LOCAL
    assert first.generated_at == GENERATED_AT
    assert first.document_count == 2
    assert first.failure_count == 0
    assert tuple(document.source.uri for document in first.documents) == (
        "local:///alpha.txt",
        "local:///zeta.txt",
    )
    assert all(document.access_groups == ("engineering",) for document in first.documents)


def test_records_recoverable_document_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_document(
        tmp_path,
        "good.txt",
        "good",
    )
    create_document(
        tmp_path,
        "unreadable.txt",
        "unreadable",
    )

    original_builder = manifest_module.build_local_metadata

    def controlled_builder(
        path: Path,
        root: Path,
        *,
        source_id: str = "local-default",
        access_groups: Iterable[str] = ("public",),
    ) -> DocumentMetadata:
        if path.name == "unreadable.txt":
            raise PermissionError("synthetic access denied")

        return original_builder(
            path,
            root,
            source_id=source_id,
            access_groups=access_groups,
        )

    monkeypatch.setattr(
        manifest_module,
        "build_local_metadata",
        controlled_builder,
    )

    manifest = build_local_manifest(
        tmp_path,
        source_id="policies",
        generated_at=GENERATED_AT,
    )

    assert manifest.document_count == 1
    assert manifest.failure_count == 1

    failure = manifest.failures[0]
    assert failure.source_id == "policies"
    assert failure.uri == "local:///unreadable.txt"
    assert failure.error_type == "PermissionError"
    assert failure.message == "synthetic access denied"


def test_rejects_timezone_naive_generation_time() -> None:
    with pytest.raises(
        ValidationError,
        match="timezone information",
    ):
        make_manifest(
            generated_at=datetime(
                2026,
                1,
                1,
                12,
                0,
            )
        )


def test_rejects_document_from_different_source(
    tmp_path: Path,
) -> None:
    document = make_metadata(
        tmp_path,
        "policy.txt",
        source_id="other-source",
    )

    with pytest.raises(
        ValidationError,
        match="documents must match source_id",
    ):
        make_manifest(documents=(document,))


def test_rejects_document_from_different_system(
    tmp_path: Path,
) -> None:
    document = make_metadata(
        tmp_path,
        "policy.txt",
    )

    with pytest.raises(
        ValidationError,
        match="documents must match source_system",
    ):
        make_manifest(
            documents=(document,),
            source_system=SourceSystem.S3,
        )


def test_rejects_failure_from_different_source() -> None:
    failure = IngestionFailure(
        source_id="other-source",
        uri="local:///failed.txt",
        error_type="OSError",
        message="synthetic failure",
    )

    with pytest.raises(
        ValidationError,
        match="failures must match source_id",
    ):
        make_manifest(failures=(failure,))


def test_rejects_duplicate_document_versions(
    tmp_path: Path,
) -> None:
    document = make_metadata(
        tmp_path,
        "policy.txt",
    )

    with pytest.raises(
        ValidationError,
        match="versions must be unique",
    ):
        make_manifest(
            documents=(document, document),
        )


def test_rejects_unstable_document_order(
    tmp_path: Path,
) -> None:
    alpha = make_metadata(
        tmp_path,
        "alpha.txt",
    )
    zeta = make_metadata(
        tmp_path,
        "zeta.txt",
    )

    with pytest.raises(
        ValidationError,
        match="stable URI ordering",
    ):
        make_manifest(
            documents=(zeta, alpha),
        )


def test_rejects_unstable_failure_order() -> None:
    alpha = IngestionFailure(
        source_id="test-source",
        uri="local:///alpha.txt",
        error_type="OSError",
        message="alpha failure",
    )
    zeta = IngestionFailure(
        source_id="test-source",
        uri="local:///zeta.txt",
        error_type="OSError",
        message="zeta failure",
    )

    with pytest.raises(
        ValidationError,
        match="stable URI ordering",
    ):
        make_manifest(
            failures=(zeta, alpha),
        )


def test_manifest_identity_changes_with_content(
    tmp_path: Path,
) -> None:
    document = create_document(
        tmp_path,
        "policy.txt",
        "version one",
    )

    first = build_local_manifest(
        tmp_path,
        source_id="policies",
        generated_at=GENERATED_AT,
    )

    document.write_text(
        "version two",
        encoding="utf-8",
    )

    second = build_local_manifest(
        tmp_path,
        source_id="policies",
        generated_at=GENERATED_AT,
    )

    assert first.manifest_id != second.manifest_id
