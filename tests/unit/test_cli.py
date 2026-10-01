from pathlib import Path

from typer.testing import CliRunner

from enterprise_document_rag.cli import app
from enterprise_document_rag.ingestion import read_manifest

runner = CliRunner()


def create_source_document(root: Path) -> Path:
    document = root / "policy.txt"
    document.write_text(
        "Synthetic access-control policy.",
        encoding="utf-8",
    )
    return document


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
    assert "manifest already exists" in second.output
    assert "use --overwrite" in second.output


def test_overwrites_existing_manifest_when_requested(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_source_document(source)
    output = tmp_path / "manifest.json"
    output.write_text("obsolete", encoding="utf-8")

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
    assert "source ID must not be empty" in result.output


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
    assert "does not exist" in result.output


def test_displays_command_help() -> None:
    result = runner.invoke(
        app,
        [
            "ingest-local",
            "--help",
        ],
    )

    assert result.exit_code == 0
    assert "Directory containing source documents" in result.stdout
    assert "--source-id" in result.stdout
    assert "--access-group" in result.stdout
    assert "--overwrite" in result.stdout
