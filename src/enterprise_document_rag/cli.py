"""Command-line interface for enterprise document ingestion."""

from pathlib import Path
from typing import Annotated

import typer

from enterprise_document_rag.ingestion import (
    build_local_manifest,
    write_manifest,
)

app = typer.Typer(
    name="document-rag",
    help="Ingest enterprise documents for processing and retrieval.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Manage enterprise document-ingestion workflows."""


@app.command("ingest-local")
def ingest_local(
    root: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="Directory containing source documents.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Destination JSON manifest.",
        ),
    ] = Path("artifacts/ingestion-manifest.json"),
    source_id: Annotated[
        str,
        typer.Option(
            "--source-id",
            help="Stable identity for this document source.",
        ),
    ] = "local-default",
    access_group: Annotated[
        list[str] | None,
        typer.Option(
            "--access-group",
            help="Authorized access group; repeat for multiple groups.",
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Replace an existing manifest.",
        ),
    ] = False,
) -> None:
    """Ingest supported local documents into a validated JSON manifest."""
    normalized_source_id = source_id.strip()
    if not normalized_source_id:
        raise typer.BadParameter(
            "source ID must not be empty",
            param_hint="--source-id",
        )

    groups = tuple(access_group or ("public",))
    manifest = build_local_manifest(
        root,
        source_id=normalized_source_id,
        access_groups=groups,
    )

    try:
        destination = write_manifest(
            manifest,
            output,
            overwrite=overwrite,
        )
    except FileExistsError as error:
        raise typer.BadParameter(
            f"manifest already exists: {output}; use --overwrite to replace it",
            param_hint="--output",
        ) from error

    typer.echo(f"Manifest: {destination}")
    typer.echo(f"Source: {manifest.source_id}")
    typer.echo(f"Documents: {manifest.document_count}")
    typer.echo(f"Failures: {manifest.failure_count}")
