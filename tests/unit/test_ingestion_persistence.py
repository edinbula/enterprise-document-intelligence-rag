from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import enterprise_document_rag.ingestion.persistence as persistence_module
from enterprise_document_rag.ingestion.manifest import (
    IngestionManifest,
    build_local_manifest,
)
from enterprise_document_rag.ingestion.persistence import (
    read_manifest,
    write_manifest,
)

GENERATED_AT = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=UTC,
)


def make_manifest(
    root: Path,
    *,
    content: str = "synthetic policy",
) -> IngestionManifest:
    root.mkdir(
        parents=True,
        exist_ok=True,
    )
    document = root / "policy.txt"
    document.write_text(
        content,
        encoding="utf-8",
    )

    return build_local_manifest(
        root,
        source_id="synthetic-policies",
        generated_at=GENERATED_AT,
    )


def test_writes_and_reads_manifest_round_trip(
    tmp_path: Path,
) -> None:
    manifest = make_manifest(tmp_path / "documents")
    destination = tmp_path / "manifest.json"

    written_path = write_manifest(
        manifest,
        destination,
    )
    restored = read_manifest(destination)

    assert written_path == destination.resolve()
    assert restored == manifest
    assert destination.read_text(encoding="utf-8").endswith("\n")


def test_creates_missing_destination_directories(
    tmp_path: Path,
) -> None:
    manifest = make_manifest(tmp_path / "documents")
    destination = tmp_path / "artifacts" / "manifests" / "manifest.json"

    write_manifest(
        manifest,
        destination,
    )

    assert destination.is_file()


def test_refuses_to_overwrite_existing_manifest(
    tmp_path: Path,
) -> None:
    manifest = make_manifest(tmp_path / "documents")
    destination = tmp_path / "manifest.json"

    write_manifest(
        manifest,
        destination,
    )

    with pytest.raises(FileExistsError):
        write_manifest(
            manifest,
            destination,
        )

    assert read_manifest(destination) == manifest


def test_overwrites_manifest_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    document_root = tmp_path / "documents"
    first = make_manifest(
        document_root,
        content="version one",
    )
    destination = tmp_path / "manifest.json"

    write_manifest(
        first,
        destination,
    )

    second = make_manifest(
        document_root,
        content="version two",
    )
    write_manifest(
        second,
        destination,
        overwrite=True,
    )

    restored = read_manifest(destination)

    assert restored == second
    assert restored.manifest_id != first.manifest_id


def test_rejects_invalid_persisted_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(
        '{"source_id": "incomplete"}',
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        read_manifest(source)


def test_missing_manifest_raises_file_not_found(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        read_manifest(tmp_path / "missing.json")


def test_removes_temporary_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = make_manifest(tmp_path / "documents")
    destination = tmp_path / "manifest.json"

    def fail_replace(
        source: Path,
        target: Path,
    ) -> None:
        raise OSError(f"synthetic replacement failure: {source} -> {target}")

    monkeypatch.setattr(
        persistence_module,
        "replace",
        fail_replace,
    )

    with pytest.raises(
        OSError,
        match="synthetic replacement failure",
    ):
        write_manifest(
            manifest,
            destination,
            overwrite=True,
        )

    temporary_files = tuple(tmp_path.glob(".manifest.json.*.tmp"))
    assert temporary_files == ()
    assert not destination.exists()
