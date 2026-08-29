#!/usr/bin/env python3
"""One-shot ``charter.yaml`` initialiser for an existing repo (#11748).

New repos get their charter from the onboarding path (materialize writes it;
the format-upgrade PR retrofits it). A repo that predates #11748 gets one
here — once — from what it actually carries:

    python scripts/charter_init.py --repo-root /path/to/repo
    python scripts/charter_init.py --repo-root /path/to/repo --check

The generated charter declares only what the audit can verify **today**: the
standard ids the repo carries as ``docs/standards/<id>/`` directories, the
template layers whose markers are present, and any ``artifacts.required``
paths that exist. Purpose and ``articles.local`` are left for a human — they
are the layers nothing checks (ADR-0143 Ruling 3), and guessing them would
put words in the repo's mouth.

Editing a charter is an ENACT, not a RATIFY (ADR-0143 Ruling 6, guard 4): a
system may not enlarge its own mandate. So this script bootstraps a file for
a human to review in a pull request, refuses to overwrite an existing
charter, and is never wired into a loop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from charter import (  # noqa: E402
    CHARTER_FILENAME,
    Articles,
    Artifacts,
    Charter,
    RailsBlock,
    render_charter,
    standard_ids_under,
)
from charter_drift_caretaker_loop import (  # noqa: E402
    audit_repo_charter,
    observe_repo,
)

#: Candidate ``artifacts.required`` paths. Only the ones that exist are
#: declared — a charter must be true the day it lands, or its first audit
#: files drift on the repo for carrying what it always carried.
_CANDIDATE_ARTIFACTS: tuple[str, ...] = (
    "docs/adr",
    "docs/arch/generated",
    "docs/standards",
    "docs/wiki",
    "tests",
)


def build_charter(repo_root: Path) -> Charter:
    """Derive a charter from what *repo_root* carries right now."""
    layers = tuple(sorted(observe_repo(repo_root, Charter()).present_layers))
    return Charter(
        articles=Articles(standards=tuple(sorted(standard_ids_under(repo_root)))),
        artifacts=Artifacts(
            required=tuple(p for p in _CANDIDATE_ARTIFACTS if (repo_root / p).exists())
        ),
        rails=RailsBlock(template_version="1", layers=layers),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repo to initialise"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the charter that would be written; write nothing",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root.resolve()
    if not repo_root.is_dir():
        print(f"not a directory: {repo_root}", file=sys.stderr)
        return 2

    target = repo_root / CHARTER_FILENAME
    charter = build_charter(repo_root)
    text = render_charter(charter)

    if args.check:
        print(text, end="")
        return 0

    if target.exists():
        print(
            f"{target} already exists — refusing to overwrite a governing "
            "declaration. Edit it deliberately, in a pull request.",
            file=sys.stderr,
        )
        return 1

    target.write_text(text, encoding="utf-8")
    report = audit_repo_charter(str(repo_root.name), repo_root)
    print(f"wrote {target}")
    for finding in report.findings:
        print(f"  {finding.finding_class}: {finding.check_id} — {finding.detail}")
    if not report.clean:
        print(
            "the generated charter does NOT audit clean — review it before committing",
            file=sys.stderr,
        )
        return 1
    print("charter drift check: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
