from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import ValidationError

import enterprise_document_rag.processing.persistence as persistence
from enterprise_document_rag.ingestion.manifest import (
    build_local_manifest,
)
from enterprise_document_rag.processing.batch import (
    ProcessingBatch,
    process_local_manifest,
)
from enterprise_document_rag.processing.persistence import (
    read_processing_batch,
    write_processing_batch,
)

GENERATED_AT = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)

UPDATED_AT = datetime(
    2026,
    1,
    2,
    12,
    0,
    tzinfo=UTC,
)


def create_batch(
    root: Path,
) -> ProcessingBatch:
    source = root / "source"
    source.mkdir(
        parents=True,
    )
    (source / "policy.txt").write_text(
        "Synthetic policy content.",
        encoding="utf-8",
    )
    (source / "register.csv").write_text(
        "id,title\n1,Synthetic policy\n",
        encoding="utf-8",
    )

    manifest = build_local_manifest(
        source,
        source_id="test-documents",
        generated_at=GENERATED_AT,
    )

    return process_local_manifest(
        source,
        manifest,
        generated_at=GENERATED_AT,
    )


def test_writes_and_reads_processing_batch(
    tmp_path: Path,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "artifacts" / "processing-batch.json"

    written = write_processing_batch(
        batch,
        destination,
    )
    restored = read_processing_batch(
        destination,
    )

    assert written == destination.resolve()
    assert restored == batch
    assert restored.document_count == 2
    assert restored.failure_count == 0


def test_creates_destination_parent_directories(
    tmp_path: Path,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "nested" / "processing" / "batch.json"

    written = write_processing_batch(
        batch,
        destination,
    )

    assert written.is_file()
    assert written.parent == destination.parent.resolve()


def test_writes_utf8_json_with_single_trailing_newline(
    tmp_path: Path,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "batch.json"

    write_processing_batch(
        batch,
        destination,
    )

    serialized = destination.read_bytes()

    assert serialized.endswith(b"\n")
    assert not serialized.endswith(b"\n\n")
    assert b"\r\n" not in serialized
    assert b'"source_id": "test-documents"' in serialized


def test_refuses_to_replace_existing_batch_by_default(
    tmp_path: Path,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "batch.json"
    destination.write_text(
        "existing content",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
    ):
        write_processing_batch(
            batch,
            destination,
        )

    assert destination.read_text(encoding="utf-8") == "existing content"


def test_overwrites_existing_batch_when_requested(
    tmp_path: Path,
) -> None:
    batch = create_batch(tmp_path)
    updated_batch = batch.model_copy(
        update={
            "generated_at": UPDATED_AT,
        }
    )
    destination = tmp_path / "batch.json"
    destination.write_text(
        "obsolete",
        encoding="utf-8",
    )

    written = write_processing_batch(
        updated_batch,
        destination,
        overwrite=True,
    )
    restored = read_processing_batch(
        destination,
    )

    assert written == destination.resolve()
    assert restored == updated_batch
    assert restored.generated_at == UPDATED_AT
    assert not tuple(destination.parent.glob(f".{destination.name}.*.tmp"))


def test_removes_temporary_file_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "batch.json"
    destination.write_text(
        "existing content",
        encoding="utf-8",
    )

    def fail_replace(
        source: Path,
        target: Path,
    ) -> NoReturn:
        del source
        del target
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(
        persistence,
        "replace",
        fail_replace,
    )

    with pytest.raises(
        OSError,
        match="synthetic replace failure",
    ):
        write_processing_batch(
            batch,
            destination,
            overwrite=True,
        )

    assert destination.read_text(encoding="utf-8") == "existing content"
    assert not tuple(destination.parent.glob(f".{destination.name}.*.tmp"))


def test_handles_failure_before_temporary_file_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = create_batch(tmp_path)
    destination = tmp_path / "batch.json"
    destination.write_text(
        "existing content",
        encoding="utf-8",
    )

    def fail_temporary_file(
        *args: object,
        **kwargs: object,
    ) -> NoReturn:
        del args
        del kwargs
        raise OSError("synthetic temporary-file failure")

    monkeypatch.setattr(
        persistence,
        "NamedTemporaryFile",
        fail_temporary_file,
    )

    with pytest.raises(
        OSError,
        match="synthetic temporary-file failure",
    ):
        write_processing_batch(
            batch,
            destination,
            overwrite=True,
        )

    assert destination.read_text(encoding="utf-8") == "existing content"
    assert not tuple(destination.parent.glob(f".{destination.name}.*.tmp"))


def test_rejects_malformed_json(
    tmp_path: Path,
) -> None:
    source = tmp_path / "malformed.json"
    source.write_text(
        "{not valid json",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
    ):
        read_processing_batch(
            source,
        )


def test_rejects_invalid_processing_batch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(
        '{"batch_id": "not-a-uuid"}',
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
    ):
        read_processing_batch(
            source,
        )


def test_rejects_missing_processing_batch(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        FileNotFoundError,
    ):
        read_processing_batch(
            tmp_path / "missing.json",
        )
