"""One-time pre-cutover extraction: Hindsight banks → wiki.

Reads every memory from the configured Hindsight instance, filters to
the subset with corroboration (≥2 citations OR tied to a closed issue),
runs them through the librarian, and writes the survivors as WikiEntry
objects in the appropriate wiki (per-repo or tribal).

Most memories are expected to drop. This is intentional — Hindsight
accumulated years of unstructured noise; the wiki should only carry
what has evidence behind it.

Run pre-cutover:

    PYTHONPATH=src uv run python scripts/extract_hindsight_to_wiki.py \\
        --dry-run

Then without --dry-run to commit. Safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repo_wiki import RepoWikiStore
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("extract_hindsight_to_wiki")


def extract_corroborated_memories(memories: list[dict]) -> list[dict]:
    """Filter memories to those with evidence.

    Rules (any-of):
      1. ≥2 citations.
      2. Exactly 1 citation AND ``closed_issue`` truthy.
    """
    survivors: list[dict] = []
    for m in memories:
        cites = m.get("citations") or []
        closed = bool(m.get("closed_issue", False))
        if len(cites) >= 2 or len(cites) == 1 and closed:
            survivors.append(m)
    return survivors


async def write_entries_to_wiki(
    *,
    store: RepoWikiStore,
    compiler: WikiCompiler,
    repo: str,
    memories: list[dict],
) -> int:
    """Route each memory through synthesize_ingest; write what comes back.

    Returns the number of entries written.
    """
    total = 0
    for m in memories:
        entries = await compiler.synthesize_ingest(
            repo=repo,
            issue_number=m.get("issue_number", 0),
            source_type="librarian",
            raw_text=m.get("text", ""),
        )
        if entries:
            store.ingest(repo, entries)
            total += len(entries)
    return total


async def _run(args: argparse.Namespace) -> int:
    """Live-run path. Imports are deferred so test imports don't fail."""
    from config import load_config  # noqa: PLC0415
    from hindsight import HindsightClient  # noqa: PLC0415
    from hindsight_types import Bank  # noqa: PLC0415
    from repo_wiki import RepoWikiStore  # noqa: PLC0415
    from tribal_wiki import TribalWikiStore  # noqa: PLC0415
    from wiki_compiler import WikiCompiler  # noqa: PLC0415

    config = load_config()
    client = HindsightClient(config=config)

    # recall_banks fetches from all banks concurrently; use a broad query to
    # surface as many memories as possible.  The corroboration filter below
    # discards noise.
    banks = [
        Bank.TRIBAL,
        Bank.TROUBLESHOOTING,
        Bank.HARNESS_INSIGHTS,
        Bank.REVIEW_INSIGHTS,
        Bank.RETROSPECTIVES,
    ]
    all_memories: list[dict] = []
    try:
        bank_results = await client.recall_banks(
            query="*",
            banks=banks,
            limit=500,
        )
        for _bank, memories in bank_results.items():
            for m in memories:
                all_memories.append(
                    {
                        "text": m.display_text,
                        "citations": m.metadata.get("citations", []),
                        "closed_issue": m.metadata.get("closed_issue", False),
                        "issue_number": m.metadata.get("issue_number", 0),
                    }
                )
    except Exception:  # noqa: BLE001
        logger.warning("recall_banks failed", exc_info=True)

    survivors = extract_corroborated_memories(all_memories)
    logger.info(
        "extracted %d survivors out of %d raw memories",
        len(survivors),
        len(all_memories),
    )

    if args.dry_run:
        return 0

    if args.repo == "global":
        store = TribalWikiStore(config.data_path("tribal"))
        effective_repo = "global"
    else:
        store = RepoWikiStore(config.data_path("repo_wiki"))
        effective_repo = args.repo

    compiler = WikiCompiler(config=config, runner=None, credentials=None)
    total = await write_entries_to_wiki(
        store=store,
        compiler=compiler,
        repo=effective_repo,
        memories=survivors,
    )
    logger.info("wrote %d entries to wiki (repo=%s)", total, effective_repo)
    return 0


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Filter and report counts; do not write.",
    )
    parser.add_argument(
        "--repo",
        default="global",
        help='Target repo slug. "global" → tribal store.',
    )
    args = parser.parse_args(argv)
    return await _run(args)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
