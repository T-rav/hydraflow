"""Background worker loop — ingest HydraFlow's own server logs.

``LogIngestLoop`` is an LLM-free caretaker loop (ADR-0029). Every cycle it
scans HydraFlow's own structured JSON-lines server log, clusters and
deduplicates recurring ERROR / WARNING messages with pure-Python
normalisation, and files a GitHub issue per surviving cluster. Those issues
carry ``find_label`` so the existing triage → plan → implement → review →
merge pipeline picks them up and the coding agents do the actual fixing — this
loop never invokes an agent.

Key safety properties:

* **Cursor-from-now** — a persisted per-file byte offset means only log lines
  appended *after* the loop first saw the file are ever ingested. The first
  run for a file just primes the cursor to EOF and files nothing, so historical
  (possibly already-fixed) errors are never back-filled.
* **Self-reference guard** — the loop's own logger and issue-creation chatter
  are skipped so it can never ingest its own activity (no feedback loop).
* **Benign allowlist** — known-noisy clusters (auth failures, credit
  exhaustion, "Repository not found", ...) are dropped before filing.
* **Hard cap** — at most ``log_ingest_max_issues_per_run`` issues per cycle,
  ERROR-first then count-descending, with anything dropped/capped logged.
* **0-sentinel guard** — ``create_issue`` returns ``0`` on failure; the dedup
  key is only recorded on a real issue number so a failed file is retried next
  cycle (the #9242 pattern).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker  # noqa: TCH004 — used in __init__ signature

logger = logging.getLogger("hydraflow.log_ingest")

# The loop's own logger and the issue-creation chatter it triggers. Lines from
# these loggers are skipped during parsing so the loop never ingests its own
# activity (a feedback loop that would file issues about filing issues).
_SELF_LOGGERS: frozenset[str] = frozenset(
    {
        "hydraflow.log_ingest",
        "hydraflow.log_ingestion",
    }
)

_KEEP_LEVELS: frozenset[str] = frozenset({"ERROR", "CRITICAL", "WARNING"})

# Marker embedded in each filed issue body for GitHub-side dedup.
_MARKER_RE = re.compile(r"<!--\s*\[log-ingest:([0-9a-f]+)\]\s*-->")

# Normalisation patterns applied (in order) to reduce a raw message to a stable
# signature. Order matters: quoted strings and paths are collapsed before bare
# numbers so that digits *inside* a path/quote don't fragment the template.
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
# Match a run of digits (optionally with a decimal part) that starts on a word
# boundary. A trailing word boundary is intentionally NOT required so that a
# number glued to a unit — ``70ms``, ``5xx``, ``30s`` — still collapses to the
# placeholder, otherwise every distinct duration/size would form its own
# cluster and defeat grouping.
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")

# Pull a likely source file out of a traceback or message for the issue body.
_SOURCE_FILE_RE = re.compile(r'File "([^"]+\.py)"|(\b[\w./-]+\.py)\b')


@dataclass
class _Cluster:
    """An accumulating group of log lines that share a normalised signature."""

    signature: str
    level: str
    count: int = 0
    example_raw: str = ""
    logger_name: str = ""
    messages: list[str] = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return self.level in {"ERROR", "CRITICAL"}

    @property
    def sighash(self) -> str:
        # Non-cryptographic dedup key only; usedforsecurity=False satisfies
        # both ruff (S324) and bandit (B324).
        return hashlib.sha1(
            f"{self.level}:{self.signature}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:16]


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


class LogIngestLoop(BaseBackgroundLoop):
    """Cluster + dedup recurring log errors/warnings into pipeline fix-issues."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        dedup: DedupStore | None = None,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(
            worker_name="log_ingest",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._prs = prs
        self._dedup = dedup
        # In-memory hot cache seeded from persistent DedupStore.
        self._filed: set[str] = dedup.get() if dedup else set()
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.log_ingest_interval

    # -- log file resolution -------------------------------------------------

    def _resolve_log_files(self) -> list[Path]:
        """Resolve the configured log file paths against ``data_root``."""
        raw = self._config.log_ingest_log_files or ""
        paths: list[Path] = []
        for part in raw.split(","):
            spec = part.strip()
            if not spec:
                continue
            p = Path(spec).expanduser()
            if not p.is_absolute():
                p = self._config.data_root / p
            paths.append(p)
        return paths

    # -- benign allowlist ----------------------------------------------------

    def _benign_patterns(self) -> list[str]:
        raw = self._config.log_ingest_benign_patterns or ""
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    def _is_benign(self, cluster: _Cluster, benign: list[str]) -> bool:
        haystack = f"{cluster.logger_name} {cluster.example_raw}".lower()
        return any(pat in haystack for pat in benign)

    # -- reading -------------------------------------------------------------

    def _read_new_lines(self, path: Path) -> tuple[list[str], int]:
        """Return (new lines, new EOF offset) for *path* since the cursor.

        Honours the cursor-from-now contract: returns an empty list (and primes
        the cursor) when there is no persisted cursor for the file yet.
        Detects truncation/rotation (file shorter than the stored cursor) and
        restarts from byte 0.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return [], 0

        stored = self._state.get_log_ingest_cursor(str(path)) if self._state else None

        if stored is None:
            # First time we've seen this file — prime to EOF, file nothing.
            return [], size

        start = stored
        if start > size:
            # File was truncated or rotated under us; restart from the top.
            logger.info(
                "log-ingest: %s shrank (%d → %d bytes) — restarting from 0",
                path,
                stored,
                size,
            )
            start = 0

        try:
            with path.open("rb") as fh:
                fh.seek(start)
                chunk = fh.read()
        except OSError:
            logger.warning("log-ingest: could not read %s", path, exc_info=True)
            return [], stored

        text = chunk.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines, size

    # -- clustering ----------------------------------------------------------

    def _cluster_lines(self, lines: list[str]) -> dict[str, _Cluster]:
        """Parse JSON log lines and group ERROR/WARNING entries by signature."""
        clusters: dict[str, _Cluster] = {}
        for line in lines:
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            level = str(data.get("level", "")).upper()
            if level not in _KEEP_LEVELS:
                continue
            logger_name = str(data.get("logger", ""))
            # Self-reference guard: never ingest our own activity.
            if logger_name in _SELF_LOGGERS:
                continue
            msg = str(data.get("msg", "")).strip()
            if not msg:
                continue
            signature = normalize_signature(msg)
            if not signature:
                continue
            # Collapse CRITICAL into ERROR for level grouping/labels.
            norm_level = "ERROR" if level in {"ERROR", "CRITICAL"} else level
            key = f"{norm_level}:{signature}"
            cluster = clusters.get(key)
            if cluster is None:
                cluster = _Cluster(
                    signature=signature,
                    level=norm_level,
                    example_raw=msg,
                    logger_name=logger_name,
                )
                clusters[key] = cluster
            cluster.count += 1
            if len(cluster.messages) < 3:
                cluster.messages.append(msg)
        return clusters

    # -- importance filter ---------------------------------------------------

    def _select_candidates(
        self, clusters: dict[str, _Cluster]
    ) -> tuple[list[_Cluster], int]:
        """Apply the importance + benign filters.

        Returns (candidate clusters, number dropped). ERROR clusters are always
        candidates; WARNING clusters only qualify at/above the configured
        minimum count. Benign-allowlist matches are always dropped.
        """
        benign = self._benign_patterns()
        warn_min = self._config.log_ingest_warning_min_count
        candidates: list[_Cluster] = []
        dropped = 0
        for cluster in clusters.values():
            if self._is_benign(cluster, benign):
                logger.debug(
                    "log-ingest: dropping benign cluster (%s, n=%d): %s",
                    cluster.level,
                    cluster.count,
                    cluster.signature[:80],
                )
                dropped += 1
                continue
            # ERROR clusters always qualify; WARNING clusters only at/above the
            # configured minimum count.
            if cluster.is_error or cluster.count >= warn_min:
                candidates.append(cluster)
            else:
                dropped += 1
        return candidates, dropped

    # -- dedup ---------------------------------------------------------------

    async def _already_filed(self, sighash: str) -> bool:
        """Check the hot cache, the DedupStore, and open GitHub issues."""
        if sighash in self._filed:
            return True
        try:
            issues = await self._prs.list_issues_by_label(self._config.log_ingest_label)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug(
                "log-ingest: GitHub dedup lookup failed for %s", sighash, exc_info=True
            )
            return False
        marker = f"<!-- [log-ingest:{sighash}] -->"
        for issue in issues:
            if marker in (issue.get("body") or ""):
                # Seed the hot cache so future cycles skip the lookup.
                self._mark_filed(sighash)
                return True
        return False

    def _mark_filed(self, sighash: str) -> None:
        self._filed.add(sighash)
        if self._dedup:
            self._dedup.add(sighash)

    # -- issue building ------------------------------------------------------

    @staticmethod
    def _suspected_source_file(cluster: _Cluster) -> str:
        for msg in cluster.messages:
            match = _SOURCE_FILE_RE.search(msg)
            if match:
                return match.group(1) or match.group(2) or ""
        return ""

    def _build_issue(self, cluster: _Cluster) -> tuple[str, str]:
        """Return (title, body) for a cluster's GitHub issue."""
        title = f"[log-ingest] {cluster.level}: {cluster.signature}"
        if len(title) > 120:
            title = title[:117] + "..."

        source = self._suspected_source_file(cluster)
        lines = [
            "## Recurring log signal",
            "",
            f"- **Level:** {cluster.level}",
            f"- **Occurrences this scan:** {cluster.count}",
            f"- **Logger:** `{cluster.logger_name or 'unknown'}`",
        ]
        if source:
            lines.append(f"- **Suspected source:** `{source}`")
        lines += [
            "",
            "### Representative log line",
            "",
            "```",
            cluster.example_raw[:1500],
            "```",
            "",
            "### Normalised signature",
            "",
            f"`{cluster.signature}`",
            "",
            "---",
            "",
            "_Filed automatically by `LogIngestLoop` from HydraFlow's own server "
            "log. Triage and fix via the normal pipeline._",
            "",
            f"<!-- [log-ingest:{cluster.sighash}] -->",
        ]
        return title, "\n".join(lines)

    # -- main cycle ----------------------------------------------------------

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.log_ingest_loop_enabled:
            return {"status": "config_disabled"}

        log_files = self._resolve_log_files()
        if not log_files:
            return {"status": "no_log_files"}

        primed = 0
        scanned_any = False
        all_clusters: dict[str, _Cluster] = {}
        pending_cursors: dict[str, int] = {}

        for path in log_files:
            path_key = str(path)
            stored = (
                self._state.get_log_ingest_cursor(path_key) if self._state else None
            )
            lines, new_eof = self._read_new_lines(path)
            pending_cursors[path_key] = new_eof
            if stored is None:
                # First run for this file: prime cursor, file nothing.
                primed += 1
                continue
            scanned_any = True
            for key, cluster in self._cluster_lines(lines).items():
                existing = all_clusters.get(key)
                if existing is None:
                    all_clusters[key] = cluster
                else:
                    existing.count += cluster.count
                    for msg in cluster.messages:
                        if len(existing.messages) < 3:
                            existing.messages.append(msg)

        # Pure first-run priming pass (every file was unprimed): advance the
        # cursors and file nothing so historical errors are not back-filled.
        if not scanned_any:
            self._persist_cursors(pending_cursors)
            return {"status": "primed", "files_primed": primed}

        candidates, dropped = self._select_candidates(all_clusters)

        # Priority order: ERROR first, then count descending.
        candidates.sort(key=lambda c: (0 if c.is_error else 1, -c.count))

        # Resolve dedup up-front so the per-run cap only counts *novel*
        # clusters — an already-filed cluster shouldn't burn cap budget.
        novel: list[_Cluster] = []
        skipped = 0
        for cluster in candidates:
            if await self._already_filed(cluster.sighash):
                skipped += 1
            else:
                novel.append(cluster)

        cap = self._config.log_ingest_max_issues_per_run
        to_file = novel[:cap]
        capped = len(novel) - len(to_file)
        if capped:
            logger.info(
                "log-ingest: per-run cap (%d) reached — deferring %d novel "
                "cluster(s) to the next cycle",
                cap,
                capped,
            )

        filed = 0
        for cluster in to_file:
            issue_number = await self._file_issue(cluster)
            if issue_number == 0:
                # 0 sentinel: do NOT record the dedup key — retry next cycle.
                logger.warning(
                    "log-ingest: create_issue returned 0 for %s — not "
                    "recording dedup key; will retry next cycle",
                    cluster.sighash,
                )
                skipped += 1
                continue
            self._mark_filed(cluster.sighash)
            filed += 1

        self._persist_cursors(pending_cursors)

        if primed:
            logger.info("log-ingest: primed %d new log file(s) this cycle", primed)

        return {
            "status": "ok",
            "filed": filed,
            "skipped": skipped,
            "dropped": dropped,
            "capped": capped,
            "files_primed": primed,
            "clusters": len(all_clusters),
        }

    async def _file_issue(self, cluster: _Cluster) -> int:
        """File a GitHub issue for *cluster*. Returns the issue number (0 on fail)."""
        title, body = self._build_issue(cluster)
        labels = [*self._config.find_label, self._config.log_ingest_label]
        try:
            return await self._prs.create_issue(title, body, labels=labels)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "log-ingest: issue creation raised for %s",
                cluster.sighash,
                exc_info=True,
            )
            return 0

    def _persist_cursors(self, cursors: dict[str, int]) -> None:
        if not self._state:
            return
        for path_key, offset in cursors.items():
            self._state.set_log_ingest_cursor(path_key, offset)
