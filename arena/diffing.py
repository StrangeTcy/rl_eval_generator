"""Lossless unified diffs for workspace submissions and inspection."""
from __future__ import annotations

import difflib
from pathlib import Path

MAX_DIFF_TEXT_BYTES = 256 * 1024


def files_differ(left: Path, right: Path) -> bool:
    """Compare files without reading an agent-created checkpoint into memory."""
    if left.stat().st_size != right.stat().st_size:
        return True
    with left.open("rb") as first, right.open("rb") as second:
        while True:
            a, b = first.read(64 * 1024), second.read(64 * 1024)
            if a != b:
                return True
            if not a:
                return False


def text_for_diff(path: Path) -> str:
    """Render small UTF-8 text, never inline binary/large workspace artifacts."""
    if not path.is_file():
        return ""
    size = path.stat().st_size
    if size > MAX_DIFF_TEXT_BYTES:
        return f"[large file contents omitted: {size} bytes]\n"
    data = path.read_bytes()
    if b"\0" in data:
        return f"[binary file contents omitted: {size} bytes]\n"
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return f"[non-UTF-8 file contents omitted: {size} bytes]\n"


def has_symlink_in_path(root: Path, rel: Path | str) -> bool:
    """Check the entire path, not just the leaf (a parent may be replaced)."""
    path = root
    for part in Path(rel).parts:
        path /= part
        if path.is_symlink():
            return True
    return False


def unified_text_diff(before: str, after: str, *, fromfile: str, tofile: str) -> str:
    """Preserve terminal newlines, including their absence, in a patch(1) diff.

    ``splitlines()`` silently treats ``"line"`` and ``"line\\n"`` as identical.
    ``difflib`` with keepends distinguishes them, but does not itself write the
    ``\\ No newline at end of file`` marker required by patch(1).
    """
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
        lineterm="\n",
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in lines
    )
