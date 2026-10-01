"""JSON persistence for typed ingestion manifests."""

from os import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from enterprise_document_rag.ingestion.manifest import (
    IngestionManifest,
)


def write_manifest(
    manifest: IngestionManifest,
    destination: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Persist a manifest as UTF-8 JSON and return its resolved path."""
    resolved_destination = destination.resolve()
    resolved_destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = manifest.model_dump_json(indent=2) + "\n"

    if not overwrite:
        with resolved_destination.open(
            "x",
            encoding="utf-8",
            newline="\n",
        ) as output:
            output.write(serialized)

        return resolved_destination

    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{resolved_destination.name}.",
            suffix=".tmp",
            dir=resolved_destination.parent,
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            temporary_path = Path(temporary.name)

        replace(
            temporary_path,
            resolved_destination,
        )
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return resolved_destination


def read_manifest(source: Path) -> IngestionManifest:
    """Read and validate one persisted ingestion manifest."""
    serialized = source.resolve().read_text(encoding="utf-8")
    return IngestionManifest.model_validate_json(serialized)
