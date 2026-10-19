"""JSON persistence for validated document-processing batches."""

from os import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from enterprise_document_rag.processing.batch import (
    ProcessingBatch,
)


def write_processing_batch(
    batch: ProcessingBatch,
    destination: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Persist a processing batch as UTF-8 JSON."""
    resolved_destination = destination.resolve()
    resolved_destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = (
        batch.model_dump_json(
            indent=2,
        )
        + "\n"
    )

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


def read_processing_batch(
    source: Path,
) -> ProcessingBatch:
    """Read and validate one persisted processing batch."""
    serialized = source.resolve().read_text(encoding="utf-8")
    return ProcessingBatch.model_validate_json(serialized)
