"""LLM-driven wiki compilation — synthesize, cross-reference, deduplicate.

This is the "librarian" from Karpathy's LLM Knowledge Base pattern.
Instead of mechanically dumping entries, the compiler uses an LLM to:

1. **Synthesize** — merge redundant entries into consolidated insights
2. **Cross-reference** — add backlinks between related entries across topics
3. **Deduplicate** — identify and merge entries covering the same concept
4. **Resolve contradictions** — flag or resolve conflicting entries

Called periodically by RepoWikiLoop and optionally after large ingests.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from circuit_breaker import CircuitBreaker
from dedup_store import DedupStore
from knowledge_metrics import metrics as _metrics
from repo_wiki import (
    DEFAULT_TOPICS,
    WikiEntry,
)
from wiki_anchor_gate import config_field_vocabulary, has_repo_anchor
from wiki_synthesis_ledger import synthesis_digest

from ._flow import WikiCompilerFlowMixin
from ._judge import WikiCompilerJudgeMixin
from ._model_io import WikiCompilerModelIOMixin
from ._prompts import _COMPILE_TOPIC_PROMPT, _SYNTHESIZE_INGEST_PROMPT

if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from events import EventBus
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore


# ---------------------------------------------------------------------------
# Contradiction-check models
# ---------------------------------------------------------------------------


logger = logging.getLogger("hydraflow.wiki_compiler")

# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class WikiCompiler(
    WikiCompilerFlowMixin,
    WikiCompilerJudgeMixin,
    WikiCompilerModelIOMixin,
):
    """LLM-powered wiki compilation and synthesis."""

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: SubprocessRunner,
        credentials: Credentials | None = None,
        event_bus: EventBus | None = None,
        gate_block_dedup: DedupStore | None = None,
    ) -> None:
        self._config = config
        self._runner = runner
        # Anchor-gate verdict of the most recent compile (#11888). The loop
        # folds these into the barren ledger; the compiler only reports.
        self._last_rejected_digests: list[str] = []
        self._last_accepted_count = 0
        if credentials is None:
            from config import Credentials as _Creds  # noqa: PLC0415

            credentials = _Creds()
        self._credentials = credentials
        # Prompt-gate block escalation (#9734 finding 3): without a bus the
        # ERROR log still fires; the SYSTEM_ALERT is simply skipped.
        self._bus = event_bus
        self._gate_block_dedup = gate_block_dedup or DedupStore(
            "prompt_gate_blocked",
            config.data_root / "dedup" / "prompt_gate_blocked.json",
        )
        # A REPEATED model failure is not transient. Measured 2026-08-30: the
        # compile call timed out at 300s, was logged as a warning, swallowed,
        # and retried on the next cycle — 71 times, ~6 hours of model spend
        # for zero output, with nothing louder than a WARNING to say so.
        #
        # The reasoning is already in this file, one branch below: a
        # prompt-gate block "is a persistent policy misconfiguration, not a
        # transient failure: every tick re-blocks, so a soft warn would be a
        # PERMANENT silent no-op". A recurring timeout is that same class and
        # was not being treated as it.
        self._model_breaker = CircuitBreaker(
            "wiki-compilation-model",
            max_failures=config.wiki_compilation_breaker_failures,
            reset_timeout=float(config.wiki_compilation_breaker_reset_seconds),
        )

    @staticmethod
    def _entry_block(entry: WikiEntry) -> str:
        """The prompt representation of one entry."""
        return (
            f"### {entry.title} (id: {entry.id})\n{entry.content}\n"
            f"Source: #{entry.source_issue or 'N/A'} ({entry.source_type})\n"
            f"Created: {entry.created_at}"
        )

    def _batch_entries(self, entries: list[WikiEntry]) -> list[list[WikiEntry]]:
        """Split *entries* into batches under the per-prompt character budget.

        Budgets by CHARACTERS rather than entry count: entries vary from a
        line to several paragraphs, so a fixed count still lets one prompt grow
        without bound — which is the defect (#11819), not a symptom of it.

        A single entry larger than the whole budget still gets its own batch.
        Dropping it would silently lose wiki content, and a batch of one is the
        smallest prompt that can carry it; if that one call times out the
        circuit breaker bounds the cost.
        """
        budget = max(self._config.wiki_compilation_batch_chars, 1)
        batches: list[list[WikiEntry]] = []
        current: list[WikiEntry] = []
        used = 0
        for entry in entries:
            size = len(self._entry_block(entry))
            if current and used + size > budget:
                batches.append(current)
                current, used = [], 0
            current.append(entry)
            used += size
        if current:
            batches.append(current)
        return batches

    async def compile_topic(
        self,
        store: RepoWikiStore,
        repo: str,
        topic: str,
        other_topics: list[str] | None = None,
    ) -> int:
        """Compile all entries in a single topic using the LLM.

        Reads current entries, asks the LLM to synthesize/deduplicate,
        then writes the compiled entries back.  Returns the number of
        entries after compilation (0 on failure).
        """

        repo_dir = store._repo_dir(repo)
        topic_path = repo_dir / f"{topic}.md"
        entries = store._load_topic_entries(topic_path)

        if len(entries) < 2:
            return len(entries)  # nothing to compile

        if other_topics is None:
            other_topics = [t for t in DEFAULT_TOPICS if t != topic]

        # Batched so ONE prompt never scales with total topic size (#11819).
        # A failed batch KEEPS ITS ORIGINAL ENTRIES rather than dropping them:
        # partial compilation must never lose wiki content, and a topic that
        # half-compiles is still strictly better than one that never can.
        batches = self._batch_entries(entries)
        compiled: list[WikiEntry] = []
        failed_batches = 0
        for batch in batches:
            prompt = _COMPILE_TOPIC_PROMPT.format(
                topic=topic,
                repo=repo,
                entries_text="\n\n".join(self._entry_block(e) for e in batch),
                other_topics=", ".join(other_topics),
            )
            raw = await self._call_model(prompt, f"compile:{topic}")
            batch_compiled = self._parse_entries(raw) if raw is not None else []
            if not batch_compiled:
                failed_batches += 1
                compiled.extend(batch)
                continue
            compiled.extend(batch_compiled)

        if failed_batches:
            logger.warning(
                "Wiki compile %s/%s: %d of %d batches failed — their entries "
                "were kept uncompiled rather than dropped",
                repo,
                topic,
                failed_batches,
                len(batches),
            )
        if failed_batches == len(batches):
            return len(entries)

        if not compiled:
            logger.warning(
                "Wiki compile for %s/%s produced no valid entries — keeping originals",
                repo,
                topic,
            )
            return len(entries)

        # Repo-specificity gate (#9954): drop anchor-less platitudes so
        # synthesis never overwrites the topic page with generic best
        # practice. Empty result → keep the originals untouched.
        compiled = self._filter_anchored_entries(
            compiled, repo=repo, topic=topic, context="compile"
        )
        if not compiled:
            logger.info(
                "Wiki compile for %s/%s: all synthesized entries lacked a "
                "repo anchor — keeping originals",
                repo,
                topic,
            )
            return len(entries)

        store._write_topic_page(topic_path, topic, compiled)
        store._rebuild_index(repo)
        store._append_log(
            repo,
            "compile",
            {
                "topic": topic,
                "before": len(entries),
                "after": len(compiled),
            },
        )

        logger.info(
            "Wiki compile %s/%s: %d entries → %d",
            repo,
            topic,
            len(entries),
            len(compiled),
        )
        return len(compiled)

    async def synthesize_ingest(
        self,
        repo: str,
        issue_number: int,
        source_type: str,
        raw_text: str,
    ) -> list[WikiEntry]:
        """Use the LLM to extract knowledge entries from raw phase output.

        Instead of mechanical section parsing, the LLM identifies durable
        insights and produces structured entries.  Returns an empty list
        on failure.
        """
        if not raw_text or len(raw_text) < 100:
            return []

        # Cap input to avoid token limits
        truncated = raw_text[:20_000]

        prompt = _SYNTHESIZE_INGEST_PROMPT.format(
            source_type=source_type,
            issue_number=issue_number,
            repo=repo,
            raw_text=truncated,
        )

        raw = await self._call_model(prompt, "synthesize_ingest")
        if raw is None:
            return []

        entries = self._parse_entries(raw)
        logger.info(
            "Wiki synthesize %s #%d (%s): %d entries extracted",
            repo,
            issue_number,
            source_type,
            len(entries),
        )
        return entries

    def _filter_anchored_entries(
        self,
        entries: list[WikiEntry],
        *,
        repo: str,
        topic: str,
        context: str,
    ) -> list[WikiEntry]:
        """Drop entries lacking a repo-specific anchor (#9954).

        A synthesized entry earns its place only if its title/content
        references something specific to this repo — a ``.py`` module, an
        ADR number, a loop/Port/runner class name, or a known config
        field. Generic best-practice platitudes ("Use ``is None`` for
        optional sentinels") dilute the wiki context injected into agent
        prompts (``max_repo_wiki_chars`` truncates) and are rejected here.
        Each drop is logged and counted so the gate stays observable and
        cannot silently regress.
        """
        vocab = config_field_vocabulary()
        kept: list[WikiEntry] = []
        self._last_rejected_digests = []
        for entry in entries:
            text = f"{entry.title}\n{entry.content}"
            if has_repo_anchor(text, config_fields=vocab):
                kept.append(entry)
                continue
            self._last_rejected_digests.append(
                synthesis_digest(entry.title, entry.content)
            )
            logger.info(
                "Wiki %s gate dropped anchor-less entry for %s/%s: %r",
                context,
                repo,
                topic,
                entry.title,
            )
        self._last_accepted_count = len(kept)
        if self._last_rejected_digests:
            _metrics.increment(
                "wiki_entries_rejected_no_anchor", len(self._last_rejected_digests)
            )
        return kept

    @property
    def last_anchor_gate_verdict(self) -> tuple[list[str], int]:
        """``(rejected digests, accepted count)`` from the most recent compile.

        The barren ledger (#11888) needs the OUTPUT of a compile, not its
        input: the input fingerprint gate (#11373) already covers the input and
        cannot tell "the topic changed" from "the outcome could change". Read
        this immediately after the compile call that produced it — it is
        overwritten by the next one, deliberately, so a caller cannot fold a
        stale verdict in.
        """
        return list(self._last_rejected_digests), self._last_accepted_count

    @staticmethod
    def _parse_entries(raw: str) -> list[WikiEntry]:
        """Parse LLM output into WikiEntry objects.

        Tolerant of markdown fences and extra text around the JSON array.
        """
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            # Remove first and last lines (fences)
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        # Find the JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Wiki compiler output has no JSON array")
            return []

        try:
            items = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Wiki compiler output is not valid JSON")
            return []

        entries: list[WikiEntry] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                raw_supersedes_ids = item.get("supersedes_ids")
                supersedes_ids = (
                    [str(x) for x in raw_supersedes_ids if isinstance(x, str | int)]
                    if isinstance(raw_supersedes_ids, list)
                    else []
                )
                entries.append(
                    WikiEntry(
                        title=item.get("title", "Untitled"),
                        content=item.get("content", ""),
                        source_type=item.get("source_type", "compiled"),
                        source_issue=item.get("source_issue"),
                        stale=item.get("stale", False),
                        supersedes_ids=supersedes_ids,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.warning("Skipping invalid entry from compiler output")

        return entries
