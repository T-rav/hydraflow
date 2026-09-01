#!/usr/bin/env python3
"""Lay one emitted vitals document into an append-only object-store path.

#11690 Layer 2. The emitter (``scripts/emit_vitals.py``) writes one
self-identifying JSON document to stdout and knows nothing about sinks. This is
the other side of that seam: it reads such a document and decides where it
lives. **Nothing here is imported by the emitter, and nothing here may be** —
that direction is the whole point of the layer split, and
``tests/test_vitals_sink.py`` asserts it.

Stdlib only, deliberately. An adapter that needed ``boto3`` would make swapping
the sink a HydraFlow dependency change, which is exactly what Layer 2 exists to
prevent. The upload is whatever the operator already uses — ``aws s3 sync``,
``rclone``, a mounted volume — against the tree this writes.

**The path carries the identity.** Partitioning by repo, host and date means a
query engine prunes by them without opening a file, and — the reason that
matters here — a document can never be silently overwritten by a different
factory: two hosts at the same SHA land in different partitions because the
host is in the path, not only in the body.

**Append-only by construction.** The leaf name includes the emission instant,
so re-emitting never replaces a prior reading. A sink that overwrote would make
"since when?" unanswerable, which is the one question Layer 3 has to answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: The emitter's own ``kind``. Spelled here rather than imported, because the
#: import would have to reach into ``scripts/`` and the whole point of the layer
#: split is that this side depends on the *document*, not on HydraFlow. It is
#: pinned against real emitter output by
#: ``test_the_kind_this_adapter_accepts_is_the_kind_the_emitter_writes`` — the
#: value is a shared vocabulary between two writers, so it gets a test rather
#: than a hope.
VITALS_KIND = "hydraflow.vitals"

#: Anything outside this becomes ``_`` in a path segment. Identity values are
#: free strings from a host, and a repo slug already contains ``/``; a branch
#: may contain anything a ref allows. Sanitising is not cosmetic — an unescaped
#: value could otherwise write outside the root it was given.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class MalformedDocument(ValueError):
    """The document is not a vitals document this layout can place."""


def _segment(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MalformedDocument(f"identity.{field} is empty; the path needs it")
    safe = _UNSAFE.sub("_", text)
    # A segment of all-dots would escape the root once joined.
    return safe if safe.strip(".") else "_"


def relative_path(document: dict[str, Any]) -> Path:
    """Where this document belongs, relative to the sink root.

    ``repo=<slug>/host=<host>/date=<YYYY-MM-DD>/<instant>-<sha7>.json``

    Hive-style ``key=value`` segments because DuckDB, Athena and Spark all read
    them as columns for free; a bare directory name would have to be parsed
    back out by every consumer separately.
    """
    if document.get("kind") != VITALS_KIND:
        raise MalformedDocument(
            f"not a {VITALS_KIND} document: kind={document.get('kind')!r}"
        )
    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        raise MalformedDocument(
            f"unsupported schema_version {version!r}; this adapter places "
            f"version {SCHEMA_VERSION}. Placing an unknown version would file "
            f"it where a reader would later mis-parse it."
        )
    identity = document.get("identity") or {}
    emitted = str(document.get("emitted_at") or "").strip()
    if not emitted:
        raise MalformedDocument("emitted_at is empty; the leaf name needs it")

    repo = _segment(identity.get("repo"), field="repo")
    host = _segment(identity.get("host"), field="host")
    sha = _segment(identity.get("head_sha"), field="head_sha")[:7]
    day = _segment(emitted[:10], field="emitted_at")
    instant = _segment(emitted, field="emitted_at")
    return (
        Path(f"repo={repo}") / f"host={host}" / f"date={day}" / f"{instant}-{sha}.json"
    )


def place(document: dict[str, Any], *, root: Path) -> Path:
    """Write *document* under *root* and return the path written.

    Refuses to overwrite. Two documents colliding on instant AND sha from one
    host is not a retry to absorb quietly — it means two emitters ran as one
    identity, and silently keeping the last would erase a reading Layer 3 would
    then never know existed.
    """
    target = root / relative_path(document)
    if target.exists():
        raise FileExistsError(
            f"{target} already exists; the sink is append-only and two "
            f"readings claiming one identity and instant is a fault, not a retry"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    return target
