import re
from pathlib import Path
from typing import Protocol

from typer.testing import CliRunner

from enterprise_document_rag.cli import app
from enterprise_document_rag.ingestion import (
    build_local_manifest,
    read_manifest,
    write_manifest,
)
from enterprise_document_rag.processing import (
    read_processing_batch,
)

runner = CliRunner()

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class CliResult(Protocol):
    """Terminal result exposing captured command output."""

    @property
    def output(self) -> str:
        """Return captured standard output and error text."""
        ...


def normalize_cli_output(
    result: CliResult,
) -> str:
    """Remove terminal styling and normalize wrapped whitespace."""
    without_ansi = _ANSI_ESCAPE.sub(
        "",
        result.output,
    )
    return " ".join(without_ansi.split())


def create_source_document(
    root: Path,
) -> Path:
    document = root / "policy.txt"
    document.write_text(
        "Synthetic access-control policy.",
        encoding="utf-8",
    )
    return document


def create_ingestion_manifest(
    source: Path,
    destination: Path,
) -> Path:
    manifest = build_local_manifest(
        source,
        source_id="northstar-documents",
    )
    return write_manifest(
        manifest,
        destination,
    )


def test_ingests_local_documents_and_writes_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    output = tmp_path / "artifacts" / "manifest.json"

    result = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--output",
            str(output),
            "--source-id",
            "northstar-documents",
            "--access-group",
            "engineering",
            "--access-group",
            "security",
        ],
    )

    assert result.exit_code == 0
    assert "Documents: 1" in result.stdout
    assert "Failures: 0" in result.stdout

    manifest = read_manifest(output)
    assert manifest.source_id == "northstar-documents"
    assert manifest.document_count == 1
    assert manifest.failure_count == 0
    assert manifest.documents[0].access_groups == (
        "engineering",
        "security",
    )


def test_uses_default_access_group(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    output = tmp_path / "manifest.json"

    result = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    manifest = read_manifest(output)
    assert manifest.source_id == "local-default"
    assert manifest.documents[0].access_groups == ("public",)


def test_refuses_to_replace_existing_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    output = tmp_path / "manifest.json"

    first = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--output",
            str(output),
        ],
    )
    second = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--output",
            str(output),
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 2

    output_text = normalize_cli_output(second)
    assert "manifest already exists" in output_text
    assert "use --overwrite" in output_text


def test_overwrites_existing_manifest_when_requested(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    output = tmp_path / "manifest.json"
    output.write_text(
        "obsolete",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--output",
            str(output),
            "--source-id",
            "replacement-source",
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    manifest = read_manifest(output)
    assert manifest.source_id == "replacement-source"


def test_rejects_empty_source_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    result = runner.invoke(
        app,
        [
            "ingest-local",
            str(source),
            "--source-id",
            "   ",
        ],
    )

    assert result.exit_code == 2
    assert "source ID must not be empty" in normalize_cli_output(result)


def test_rejects_missing_source_directory(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "ingest-local",
            str(tmp_path / "missing"),
        ],
    )

    assert result.exit_code == 2
    assert "does not exist" in normalize_cli_output(result)


def test_displays_ingestion_command_help() -> None:
    result = runner.invoke(
        app,
        [
            "ingest-local",
            "--help",
        ],
    )

    assert result.exit_code == 0

    output_text = normalize_cli_output(result)
    assert "Directory containing source documents" in output_text
    assert "--source-id" in output_text
    assert "--access-group" in output_text
    assert "--overwrite" in output_text


def test_processes_local_ingestion_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    (source / "register.csv").write_text(
        "id,title\n1,Synthetic policy\n",
        encoding="utf-8",
    )

    manifest_path = tmp_path / "artifacts" / "manifest.json"
    create_ingestion_manifest(
        source,
        manifest_path,
    )
    output = tmp_path / "artifacts" / "processing-batch.json"

    result = runner.invoke(
        app,
        [
            "process-local",
            str(source),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Documents: 2" in result.stdout
    assert "Processing failures: 0" in result.stdout
    assert "Ingestion failures: 0" in result.stdout

    batch = read_processing_batch(output)
    assert batch.document_count == 2
    assert batch.failure_count == 0
    assert batch.ingestion_failure_count == 0


def test_records_processing_failure_from_cli(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "unsupported.pdf").write_bytes(b"synthetic pdf")

    manifest_path = tmp_path / "manifest.json"
    create_ingestion_manifest(
        source,
        manifest_path,
    )
    output = tmp_path / "batch.json"

    result = runner.invoke(
        app,
        [
            "process-local",
            str(source),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Documents: 0" in result.stdout
    assert "Processing failures: 1" in result.stdout

    batch = read_processing_batch(output)
    assert batch.document_count == 0
    assert batch.failure_count == 1


def test_refuses_to_replace_existing_processing_batch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)

    manifest_path = tmp_path / "manifest.json"
    create_ingestion_manifest(
        source,
        manifest_path,
    )
    output = tmp_path / "batch.json"
    output.write_text(
        "existing content",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "process-local",
            str(source),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2

    output_text = normalize_cli_output(result)
    assert "processing batch already exists" in output_text
    assert "use --overwrite" in output_text
    assert output.read_text(encoding="utf-8") == "existing content"


def test_overwrites_existing_processing_batch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)

    manifest_path = tmp_path / "manifest.json"
    create_ingestion_manifest(
        source,
        manifest_path,
    )
    output = tmp_path / "batch.json"
    output.write_text(
        "obsolete",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "process-local",
            str(source),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    batch = read_processing_batch(output)
    assert batch.document_count == 1


def test_rejects_missing_processing_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    result = runner.invoke(
        app,
        [
            "process-local",
            str(source),
            "--manifest",
            str(tmp_path / "missing.json"),
        ],
    )

    assert result.exit_code == 2
    assert "does not exist" in normalize_cli_output(result)


def test_displays_processing_command_help() -> None:
    result = runner.invoke(
        app,
        [
            "process-local",
            "--help",
        ],
    )

    assert result.exit_code == 0

    output_text = normalize_cli_output(result)
    assert "Process a local ingestion manifest" in output_text
    assert "root" in output_text
    assert "--manifest" in output_text
    assert "--output" in output_text
    assert "--overwrite" in output_text
