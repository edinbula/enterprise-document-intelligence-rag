from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from enterprise_document_rag.ingestion.manifest import (
    IngestionFailure,
    IngestionManifest,
    build_local_manifest,
)
from enterprise_document_rag.ingestion.models import SourceSystem
from enterprise_document_rag.processing.batch import (
    ProcessingBatch,
    ProcessingFailure,
    _resolve_local_document,
    process_local_manifest,
)

GENERATED_AT = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)

BATCH_ID = UUID("44444444-4444-4444-4444-444444444444")


def create_manifest(
    root: Path,
    *,
    source_id: str = "test-source",
) -> IngestionManifest:
    return build_local_manifest(
        root,
        source_id=source_id,
        generated_at=GENERATED_AT,
    )


def test_processes_mixed_local_manifest_in_stable_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "zeta.txt").write_text(
        "Zeta paragraph.",
        encoding="utf-8",
    )
    (tmp_path / "alpha.csv").write_text(
        "id,name\n1,Alpha\n",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)

    batch = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert batch.manifest_id == manifest.manifest_id
    assert batch.generated_at == GENERATED_AT
    assert batch.document_count == 2
    assert batch.failure_count == 0
    assert batch.ingestion_failure_count == 0
    assert tuple(document.source.source.uri for document in batch.documents) == (
        "local:///alpha.csv",
        "local:///zeta.txt",
    )
    assert all(document.processed_at == GENERATED_AT for document in batch.documents)


def test_builds_deterministic_batch_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)

    first = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )
    second = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert first.batch_id == second.batch_id
    assert first.documents == second.documents
    assert first.failures == second.failures


def test_uses_current_utc_time_by_default(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)

    before = datetime.now(UTC)
    batch = process_local_manifest(
        tmp_path,
        manifest,
    )
    after = datetime.now(UTC)

    assert before <= batch.generated_at <= after
    assert batch.generated_at.tzinfo is not None
    assert batch.generated_at.utcoffset() is not None


def test_recovers_when_document_content_changes(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_text(
        "Original content.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)

    document.write_text(
        "Changed content.",
        encoding="utf-8",
    )

    batch = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert batch.document_count == 0
    assert batch.failure_count == 1
    assert batch.failures[0].source_uri == "local:///policy.txt"
    assert batch.failures[0].error_type == "ValueError"
    assert batch.failures[0].message == "document content does not match ingestion metadata"


def test_recovers_when_document_is_missing(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)
    document.unlink()

    batch = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert batch.document_count == 0
    assert batch.failure_count == 1
    assert batch.failures[0].source_uri == "local:///policy.txt"
    assert batch.failures[0].error_type in {
        "FileNotFoundError",
        "ValueError",
    }


def test_continues_after_one_document_fails(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "alpha.txt"
    invalid = tmp_path / "zeta.txt"

    valid.write_text(
        "Valid content.",
        encoding="utf-8",
    )
    invalid.write_text(
        "Original content.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)

    invalid.write_text(
        "Modified content.",
        encoding="utf-8",
    )

    batch = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert batch.document_count == 1
    assert batch.failure_count == 1
    assert batch.documents[0].source.source.uri == "local:///alpha.txt"
    assert batch.failures[0].source_uri == "local:///zeta.txt"


def test_records_malformed_pdf_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.pdf").write_bytes(b"synthetic pdf")
    manifest = create_manifest(tmp_path)

    batch = process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )

    assert batch.document_count == 0
    assert batch.failure_count == 1
    assert batch.failures[0].source_uri == "local:///policy.pdf"
    assert batch.failures[0].error_type == "ValueError"
    assert batch.failures[0].message == "PDF document could not be read"


def test_preserves_ingestion_failure_count(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)
    manifest_with_failure = manifest.model_copy(
        update={
            "failures": (
                IngestionFailure(
                    source_id=manifest.source_id,
                    uri="local:///unavailable.txt",
                    error_type="OSError",
                    message="source unavailable",
                ),
            )
        }
    )

    batch = process_local_manifest(
        tmp_path,
        manifest_with_failure,
        generated_at=GENERATED_AT,
    )

    assert batch.document_count == 1
    assert batch.failure_count == 0
    assert batch.ingestion_failure_count == 1


def test_rejects_missing_document_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(source)

    with pytest.raises(
        ValueError,
        match="document root is not a directory",
    ):
        process_local_manifest(
            tmp_path / "missing",
            manifest,
            generated_at=GENERATED_AT,
        )


def test_rejects_non_local_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)
    non_local_manifest = manifest.model_copy(
        update={
            "source_system": SourceSystem.S3,
        }
    )

    with pytest.raises(
        ValueError,
        match="requires a local manifest",
    ):
        process_local_manifest(
            tmp_path,
            non_local_manifest,
            generated_at=GENERATED_AT,
        )


def test_rejects_non_local_document_metadata(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    metadata = create_manifest(tmp_path).documents[0]
    non_local_source = metadata.source.model_copy(
        update={
            "system": SourceSystem.S3,
        }
    )
    non_local_metadata = metadata.model_copy(
        update={
            "source": non_local_source,
        }
    )

    with pytest.raises(
        ValueError,
        match="requires local source metadata",
    ):
        _resolve_local_document(
            tmp_path,
            non_local_metadata,
        )


def test_rejects_local_uri_without_required_prefix(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    metadata = create_manifest(tmp_path).documents[0]
    invalid_source = metadata.source.model_copy(
        update={
            "uri": "policy.txt",
        }
    )
    invalid_metadata = metadata.model_copy(
        update={
            "source": invalid_source,
        }
    )

    with pytest.raises(
        ValueError,
        match="must begin with local:///",
    ):
        _resolve_local_document(
            tmp_path,
            invalid_metadata,
        )


@pytest.mark.parametrize(
    "uri",
    [
        "local:///",
        "local:///../secret.txt",
        "local:////absolute.txt",
    ],
)
def test_rejects_unsafe_local_uri(
    tmp_path: Path,
    uri: str,
) -> None:
    (tmp_path / "policy.txt").write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    metadata = create_manifest(tmp_path).documents[0]
    invalid_source = metadata.source.model_copy(
        update={
            "uri": uri,
        }
    )
    invalid_metadata = metadata.model_copy(
        update={
            "source": invalid_source,
        }
    )

    with pytest.raises(
        ValueError,
        match="contains an unsafe path",
    ):
        _resolve_local_document(
            tmp_path,
            invalid_metadata,
        )


def test_rejects_local_uri_resolving_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    document = root / "policy.txt"
    document.write_text(
        "Synthetic policy.",
        encoding="utf-8",
    )
    metadata = create_manifest(root).documents[0]
    outside = tmp_path / "outside.txt"

    original_resolve = Path.resolve

    def resolve_path(
        path: Path,
        strict: bool = False,
    ) -> Path:
        if path == document:
            return original_resolve(
                outside,
                strict=strict,
            )
        return original_resolve(
            path,
            strict=strict,
        )

    monkeypatch.setattr(
        Path,
        "resolve",
        resolve_path,
    )

    with pytest.raises(
        ValueError,
        match="resolves outside the configured root",
    ):
        _resolve_local_document(
            root,
            metadata,
        )


def build_valid_batch(
    tmp_path: Path,
) -> ProcessingBatch:
    (tmp_path / "alpha.txt").write_text(
        "Alpha content.",
        encoding="utf-8",
    )
    (tmp_path / "zeta.txt").write_text(
        "Zeta content.",
        encoding="utf-8",
    )
    manifest = create_manifest(tmp_path)
    return process_local_manifest(
        tmp_path,
        manifest,
        generated_at=GENERATED_AT,
    )


def make_failure(
    *,
    document_id: UUID,
    version_id: UUID,
    source_uri: str,
) -> ProcessingFailure:
    return ProcessingFailure(
        document_id=document_id,
        version_id=version_id,
        source_uri=source_uri,
        error_type="ValueError",
        message="synthetic failure",
    )


def test_rejects_naive_batch_timestamp(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)

    with pytest.raises(
        ValidationError,
        match="must include timezone information",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=datetime(
                2026,
                1,
                1,
                12,
                0,
            ),
            documents=batch.documents,
            ingestion_failure_count=0,
        )


def test_rejects_duplicate_processed_versions(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)
    document = batch.documents[0]

    with pytest.raises(
        ValidationError,
        match="processed document versions must be unique",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=GENERATED_AT,
            documents=(
                document,
                document,
            ),
            ingestion_failure_count=0,
        )


def test_rejects_duplicate_failure_versions(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)
    document = batch.documents[0]
    failure = make_failure(
        document_id=document.source.document_id,
        version_id=document.source.version_id,
        source_uri="local:///failed.txt",
    )

    with pytest.raises(
        ValidationError,
        match="processing failure versions must be unique",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=GENERATED_AT,
            failures=(
                failure,
                failure,
            ),
            ingestion_failure_count=0,
        )


def test_rejects_version_that_both_succeeds_and_fails(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)
    document = batch.documents[0]
    failure = make_failure(
        document_id=document.source.document_id,
        version_id=document.source.version_id,
        source_uri=document.source.source.uri,
    )

    with pytest.raises(
        ValidationError,
        match="cannot both succeed and fail",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=GENERATED_AT,
            documents=(document,),
            failures=(failure,),
            ingestion_failure_count=0,
        )


def test_rejects_unstable_processed_document_order(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)

    with pytest.raises(
        ValidationError,
        match="must use stable URI ordering",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=GENERATED_AT,
            documents=tuple(reversed(batch.documents)),
            ingestion_failure_count=0,
        )


def test_rejects_unstable_failure_order(
    tmp_path: Path,
) -> None:
    batch = build_valid_batch(tmp_path)
    first_document = batch.documents[0]
    second_document = batch.documents[1]

    alpha_failure = make_failure(
        document_id=first_document.source.document_id,
        version_id=first_document.source.version_id,
        source_uri="local:///alpha.txt",
    )
    zeta_failure = make_failure(
        document_id=second_document.source.document_id,
        version_id=second_document.source.version_id,
        source_uri="local:///zeta.txt",
    )

    with pytest.raises(
        ValidationError,
        match="must use stable URI ordering",
    ):
        ProcessingBatch(
            batch_id=BATCH_ID,
            manifest_id=batch.manifest_id,
            generated_at=GENERATED_AT,
            failures=(
                zeta_failure,
                alpha_failure,
            ),
            ingestion_failure_count=0,
        )
