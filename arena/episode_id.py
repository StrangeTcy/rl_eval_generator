"""Validate host-side episode names before using them as filesystem paths."""
from __future__ import annotations

import re


def validate_episode_id(episode_id: str) -> str:
    """Return a single safe path component, or reject traversal and separators."""
    if not isinstance(episode_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", episode_id
    ):
        raise ValueError("Invalid episode ID: expected 1-128 safe ASCII characters")
    return episode_id
