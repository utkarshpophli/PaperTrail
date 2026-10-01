"""Filesystem storage helpers for uploaded PDFs and extracted figures.

Every paper's files live under ``{storage_dir}/{paper_id}/`` so deleting a
paper is a single directory removal, and the document-processing pipeline
gets a stable ``output_dir`` to extract figures into.

These are all real filesystem I/O calls, so callers reach them only through
``starlette.concurrency.run_in_threadpool`` — never a direct blocking call
from an async route or background task (CLAUDE.md: no blocking I/O in async
handlers). ``paper_dir_path`` is the one exception: it does pure path
arithmetic and touches nothing on disk.
"""

import re
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class UnsafeFilenameError(ValueError):
    """Raised when a user-supplied filename can't be made filesystem-safe."""


def safe_filename(original_name: str) -> str:
    """Strips any directory component and unsafe characters so a
    user-supplied filename can never escape its target directory
    (docs/SECURITY.md) — sanitized before it ever touches disk.
    """
    name = Path(original_name).name  # drops directory components, incl. ".."
    name = _SAFE_CHARS.sub("_", name).lstrip(".")
    if not name:
        raise UnsafeFilenameError(f"Cannot derive a safe filename from {original_name!r}")
    return name


def paper_dir_path(paper_id: UUID) -> Path:
    """Pure path computation — does not touch the filesystem."""
    return Path(get_settings().storage_dir) / str(paper_id)


def ensure_paper_dir(paper_id: UUID) -> Path:
    """Creates (if needed) and returns the per-paper storage directory.
    Blocking — call only via ``run_in_threadpool``.
    """
    directory = paper_dir_path(paper_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_file(directory: Path, filename: str, content: bytes) -> Path:
    """Writes ``content`` under ``directory`` using a sanitized version of
    ``filename``. Blocking — call only via ``run_in_threadpool``.
    """
    dest = directory / safe_filename(filename)
    dest.write_bytes(content)
    return dest
