"""Stable signature keys for log lines and tool/subprocess errors.

Extracted from ``log_ingest_loop`` so the retrospective's signal extraction
clusters errors exactly the way log ingestion does. Two copies would drift and
cluster the same error two different ways.
"""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_ISSUE_PR_RE = re.compile(r"#\d+")
_PATH_RE = re.compile(r"(?:/[\w.+-]+)+(?:/)?|[\w.+-]+/[\w./+-]+")
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{8,}\b")
_DQ_RE = re.compile(r'"[^"]*"')
_SQ_RE = re.compile(r"'[^']*'")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")


def normalize_signature(msg: str) -> str:
    """Reduce a raw log message to a stable signature key.

    Strips the variable parts of a message (timestamps, UUIDs, issue/PR
    numbers, file paths, hex/uuid hashes, quoted strings, bare digits) to
    placeholders so that otherwise-identical errors cluster together
    regardless of their per-occurrence specifics.
    """
    text = msg.strip()
    text = _TIMESTAMP_RE.sub("<TS>", text)
    text = _UUID_RE.sub("<UUID>", text)
    text = _DQ_RE.sub("<STR>", text)
    text = _SQ_RE.sub("<STR>", text)
    text = _ISSUE_PR_RE.sub("#<N>", text)
    text = _PATH_RE.sub("<PATH>", text)
    text = _HEX_RE.sub("<HASH>", text)
    text = _NUM_RE.sub("<N>", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()
