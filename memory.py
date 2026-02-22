"""Memory digest system for persistent agent learnings."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from file_util import atomic_write
from models import MemoryIssueData, MemorySyncResult
from state import StateTracker
from subprocess_util import make_clean_env

if TYPE_CHECKING:
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.memory")


def parse_memory_suggestion(transcript: str) -> dict[str, str] | None:
    """Parse a MEMORY_SUGGESTION block from an agent transcript.

    Returns a dict with ``title``, ``learning``, and ``context`` keys,
    or ``None`` if no block is found.  Only the first block is returned
    (cap at 1 suggestion per agent run).
    """
    pattern = r"MEMORY_SUGGESTION_START\s*\n(.*?)\nMEMORY_SUGGESTION_END"
    match = re.search(pattern, transcript, re.DOTALL)
    if not match:
        return None

    block = match.group(1)
    result: dict[str, str] = {"title": "", "learning": "", "context": ""}

    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("title:"):
            result["title"] = stripped[len("title:") :].strip()
        elif stripped.startswith("learning:"):
            result["learning"] = stripped[len("learning:") :].strip()
        elif stripped.startswith("context:"):
            result["context"] = stripped[len("context:") :].strip()

    if not result["title"] or not result["learning"]:
        return None

    return result


def build_memory_issue_body(
    learning: str, context: str, source: str, reference: str
) -> str:
    """Format a structured GitHub issue body for a memory suggestion."""
    return (
        f"## Memory Suggestion\n\n"
        f"**Learning:** {learning}\n\n"
        f"**Context:** {context}\n\n"
        f"**Source:** {source} during {reference}\n"
    )


def load_memory_digest(config: HydraFlowConfig) -> str:
    """Read the memory digest from disk if it exists.

    Returns an empty string if the file is missing or empty.
    Content is capped at ``config.max_memory_prompt_chars``.
    """
    digest_path = config.repo_root / ".hydraflow" / "memory" / "digest.md"
    if not digest_path.is_file():
        return ""
    try:
        content = digest_path.read_text()
    except OSError:
        return ""
    if not content.strip():
        return ""
    max_chars = config.max_memory_prompt_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n…(truncated)"
    return content


async def file_memory_suggestion(
    transcript: str,
    source: str,
    reference: str,
    config: HydraFlowConfig,
    prs: PRManager,
    state: StateTracker,
) -> None:
    """Parse and file a memory suggestion from an agent transcript."""
    suggestion = parse_memory_suggestion(transcript)
    if not suggestion:
        return

    body = build_memory_issue_body(
        learning=suggestion["learning"],
        context=suggestion["context"],
        source=source,
        reference=reference,
    )
    title = f"[Memory] {suggestion['title']}"

    if config.memory_auto_approve:
        # Skip HITL — label directly for memory sync pickup
        labels = list(config.memory_label)
        issue_num = await prs.create_issue(title, body, labels)
        if issue_num:
            logger.info(
                "Auto-approved memory suggestion as issue #%d: %s",
                issue_num,
                suggestion["title"],
            )
    else:
        # Standard flow — route through HITL for human approval
        labels = list(config.improve_label) + list(config.hitl_label)
        issue_num = await prs.create_issue(title, body, labels)
        if issue_num:
            state.set_hitl_origin(issue_num, config.improve_label[0])
            state.set_hitl_cause(issue_num, "Memory suggestion")
            logger.info(
                "Filed memory suggestion as issue #%d: %s",
                issue_num,
                suggestion["title"],
            )


class MemorySyncWorker:
    """Polls ``hydraflow-memory`` issues and compiles them into a local digest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._state = state
        self._bus = event_bus

    async def sync(self, issues: list[MemoryIssueData]) -> MemorySyncResult:
        """Main sync entry point.

        *issues* is a list of dicts with ``number``, ``title``, ``body``,
        and ``createdAt`` keys (from ``gh issue list --json``).

        Returns stats dict for event publishing.
        """
        current_ids = sorted(i["number"] for i in issues)
        prev_ids, prev_hash, _ = self._state.get_memory_state()

        if not issues:
            self._state.update_memory_state([], prev_hash)
            return {
                "action": "synced",
                "item_count": 0,
                "compacted": False,
                "digest_chars": 0,
            }

        # Check if issue set changed
        if current_ids == sorted(prev_ids):
            # No change — just update timestamp
            self._state.update_memory_state(current_ids, prev_hash)
            digest_path = self._config.repo_root / ".hydraflow" / "memory" / "digest.md"
            digest_chars = len(digest_path.read_text()) if digest_path.is_file() else 0
            return {
                "action": "synced",
                "item_count": len(issues),
                "compacted": False,
                "digest_chars": digest_chars,
            }

        # Extract learnings and build digest
        learnings: list[tuple[int, str, str]] = []
        for issue in issues:
            learning = self._extract_learning(issue.get("body", ""))
            created = issue.get("createdAt", "")
            if learning:
                learnings.append((issue["number"], learning, created))

        # Sort newest first
        learnings.sort(key=lambda x: x[2], reverse=True)

        # Build digest
        compacted = False
        digest = self._build_digest(learnings)
        max_chars = self._config.max_memory_chars
        if len(digest) > max_chars:
            digest = await self._compact_digest(learnings, max_chars)
            compacted = True

        # Write individual items
        items_dir = self._config.repo_root / ".hydraflow" / "memory" / "items"
        items_dir.mkdir(parents=True, exist_ok=True)
        for num, learning, _ in learnings:
            item_path = items_dir / f"{num}.md"
            item_path.write_text(learning)

        # Atomic write of digest
        self._write_digest(digest)

        # Update state
        digest_hash = hashlib.sha256(digest.encode()).hexdigest()[:16]
        self._state.update_memory_state(current_ids, digest_hash)

        return {
            "action": "synced",
            "item_count": len(learnings),
            "compacted": compacted,
            "digest_chars": len(digest),
        }

    @staticmethod
    def _extract_learning(body: str) -> str:
        """Extract the learning content from an issue body.

        Looks for a ``## Memory Suggestion`` section with a
        ``**Learning:**`` line.  Falls back to the full body.
        """
        if not body or not body.strip():
            return ""

        # Try structured extraction
        learning_match = re.search(
            r"\*\*Learning:\*\*\s*(.+?)(?=\n\*\*|\n##|\Z)",
            body,
            re.DOTALL,
        )
        if learning_match:
            return learning_match.group(1).strip()

        # Fallback: return full body (stripped)
        return body.strip()

    @staticmethod
    def _build_digest(learnings: list[tuple[int, str, str]]) -> str:
        """Build the digest markdown from ``(issue_number, learning, created_at)`` tuples."""
        now = datetime.now(UTC).isoformat()
        header = (
            f"## Accumulated Learnings\n"
            f"*{len(learnings)} learnings — last synced {now}*\n"
        )
        sections = []
        for num, learning, _ in learnings:
            sections.append(f"- **#{num}:** {learning}")
        return header + "\n" + "\n---\n".join(sections) + "\n"

    async def _compact_digest(
        self, learnings: list[tuple[int, str, str]], max_chars: int
    ) -> str:
        """Deduplicate and optionally summarise learnings to fit within *max_chars*.

        Pipeline:
        1. Keyword-overlap deduplication (>70% overlap → drop duplicate).
        2. Rebuild digest from unique items.
        3. If still over *max_chars*: call a cheap model to summarise.
        4. Final truncation safety-net in case the model returns too much.
        """
        # --- Step 1: Deduplicate by keyword overlap ---
        seen_keywords: list[set[str]] = []
        unique: list[tuple[int, str, str]] = []

        for num, learning, created in learnings:
            words = {
                w.lower() for w in re.findall(r"[a-zA-Z]+", learning) if len(w) >= 4
            }
            is_dup = False
            for existing in seen_keywords:
                if not words or not existing:
                    continue
                overlap = len(words & existing) / max(len(words), 1)
                if overlap > 0.7:
                    is_dup = True
                    break
            if not is_dup:
                unique.append((num, learning, created))
                seen_keywords.append(words)

        # --- Step 2: Build digest from unique items ---
        now = datetime.now(UTC).isoformat()
        header = (
            f"## Accumulated Learnings\n"
            f"*{len(unique)} learnings (compacted) — last synced {now}*\n"
        )
        sections = []
        for num, learning, _ in unique:
            sections.append(f"- **#{num}:** {learning}")

        digest = header + "\n" + "\n---\n".join(sections) + "\n"

        # --- Step 3: Model-based summarisation if still over limit ---
        if len(digest) > max_chars:
            summarised = await self._summarise_with_model(digest, max_chars)
            if summarised:
                digest = summarised

        # --- Step 4: Final truncation safety-net ---
        if len(digest) > max_chars:
            digest = digest[:max_chars] + "\n\n…(truncated)"

        return digest

    async def _summarise_with_model(self, content: str, max_chars: int) -> str | None:
        """Use a cheap model to condense the digest.

        Returns the summarised text or ``None`` on failure (caller
        falls back to truncation).
        """
        model = self._config.memory_compaction_model
        prompt = (
            f"Condense the following agent learnings into at most {max_chars} characters. "
            "Preserve every distinct insight but merge overlapping ones. "
            "Output ONLY the condensed markdown list — no preamble.\n\n"
            f"{content}"
        )
        cmd = ["claude", "-p", "--model", model]
        env = make_clean_env(self._config.gh_token)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()), timeout=60
            )
            if proc.returncode != 0:
                logger.warning(
                    "Memory compaction model failed (rc=%d): %s",
                    proc.returncode,
                    stderr.decode().strip()[:200],
                )
                return None
            result = stdout.decode().strip()
            if not result:
                return None
            now = datetime.now(UTC).isoformat()
            return (
                f"## Accumulated Learnings\n"
                f"*Summarised — last synced {now}*\n\n"
                f"{result}\n"
            )
        except TimeoutError:
            logger.warning("Memory compaction model timed out")
            return None
        except (OSError, FileNotFoundError) as exc:
            logger.warning("Memory compaction model unavailable: %s", exc)
            return None

    def _write_digest(self, content: str) -> None:
        """Write digest to disk atomically."""
        digest_path = self._config.repo_root / ".hydraflow" / "memory" / "digest.md"
        atomic_write(digest_path, content)

    async def publish_sync_event(self, stats: MemorySyncResult) -> None:
        """Publish a MEMORY_SYNC event with *stats*."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.MEMORY_SYNC,
                data=dict(stats),
            )
        )
