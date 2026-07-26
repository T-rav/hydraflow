"""Operator CLI: record a human resolution for an escape-ledger finding (#10574).

The trigger surface for ``EscapeLedger.append_resolution``. Every ``escape-ledger``
HITL issue asks a human to point at the encoding that closes an escape out
(regression-test / stored-lesson / detector / ADR); this is where they record
that answer, appending a superseding resolution row so ``encoded_as`` stops being
``none-yet`` and ``EscapeLedgerLoop`` (#10577) closes the stranded HITL issue on
its next tick.

Usage (from the repo root; the Makefile ``escape-resolve`` / ``escape-list``
targets wrap these with ``PYTHONPATH=src``)::

    python scripts/resolve_escape.py list
    python scripts/resolve_escape.py resolve <escape-id> --encoded-as regression-test \
        --confidence high --notes "pinned by tests/regressions/test_x.py"

Filesystem-only: it reads and appends the append-only JSONL ledger, no git / gh /
network. ``--ledger-path`` overrides the default repo-scoped location resolved
from config.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from escape.resolve import (  # noqa: E402
    VALID_CONFIDENCES,
    VALID_ENCODINGS,
    EscapeResolveError,
    default_ledger_path,
    list_unresolved,
    resolve_escape,
)


def build_parser() -> argparse.ArgumentParser:
    """Argparse CLI: a ``resolve`` recorder and a ``list`` discovery helper."""
    parser = argparse.ArgumentParser(
        prog="resolve_escape",
        description="Record a human resolution for an escape-ledger finding.",
    )
    # Shared so --ledger-path is accepted AFTER the subcommand (the natural
    # operator order: `resolve <id> --encoded-as X --ledger-path Y`), which a
    # parent-level optional would reject.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--ledger-path",
        default=None,
        help="Escape-ledger JSONL path (defaults to the repo-scoped location).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser(
        "resolve",
        parents=[common],
        help="Record a resolution (encoding) for one escape id.",
    )
    resolve.add_argument("escape_id", help="The escape id, e.g. 'bug-issue:9196f74'.")
    resolve.add_argument(
        "--encoded-as",
        required=True,
        choices=list(VALID_ENCODINGS),
        help="How the escape was encoded (closes it out).",
    )
    resolve.add_argument(
        "--confidence",
        default=None,
        choices=list(VALID_CONFIDENCES),
        help="Optionally confirm the attribution confidence (bumping off 'low' "
        "answers a low-confidence surfacing).",
    )
    resolve.add_argument(
        "--notes", default=None, help="Optional free-text note recorded on the row."
    )

    sub.add_parser(
        "list",
        parents=[common],
        help="List the escapes still awaiting a resolution.",
    )
    return parser


def _ledger_path(raw: str | None) -> Path:
    """The explicit ``--ledger-path`` if given, else the repo-scoped default."""
    if raw:
        return Path(raw)
    return default_ledger_path(HydraFlowConfig())


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns a process exit code (0 ok, 2 on operator-input error)."""
    args = build_parser().parse_args(argv)
    ledger_path = _ledger_path(args.ledger_path)

    if args.command == "list":
        unresolved = list_unresolved(ledger_path)
        if not unresolved:
            print(f"No unresolved escapes in {ledger_path}.")
            return 0
        print(f"{len(unresolved)} unresolved escape(s) in {ledger_path}:")
        for record in unresolved:
            print(
                f"  {record.id}\t(detected {record.detected_at}, "
                f"confidence {record.attribution_confidence})"
            )
        return 0

    try:
        record = resolve_escape(
            args.escape_id,
            args.encoded_as,
            ledger_path=ledger_path,
            attribution_confidence=args.confidence,
            notes=args.notes,
        )
    except EscapeResolveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"Recorded resolution for {record.id}: encoded_as={record.encoded_as}, "
        f"confidence={record.attribution_confidence}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
