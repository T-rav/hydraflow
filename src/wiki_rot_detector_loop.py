"""WikiRotDetectorLoop — weekly wiki cite freshness detector (spec §4.9).

Walks every ``RepoWikiStore``-registered repo, extracts cited code
references from each wiki entry via three patterns (``path.py:symbol``,
dotted ``src.module.Class``, and bare identifiers inside ``python``
fences — hints only), and verifies each hard cite against:

- **HydraFlow-self** (``config.repo_root``) via AST introspection —
  catches re-exports and ``__init__.py`` re-bindings that grep misses.
- **Managed repos** via grep over wiki markdown mirrors only — full
  AST verification across every managed repo is out of scope for v1
  and noted below as a follow-up.

A second **shipped-claim pass** (issue #9598) verifies structured
``fixed_in_pr`` assertions in ``json:entry`` blocks: a claim that a fix
shipped in ``#NNNN`` is corroborated iff at least one of its ``code_refs``
resolves against the checked-out source. An uncorroborated claim is the
#9455-shape drift ("shipped" asserted, no surviving code) and files an
entry-level finding naming the PR; its dead refs are suppressed from the
per-cite pass so each stale claim yields one finding, not N. Verifying the
cited PR actually *merged* (network ``get_pr_merge_state``) is the split-out
follow-up #9664; auto-memory notes outside the repo are out of CI scope
(#9935). Self-repo only — corroboration needs AST over real source.

For each broken cite the loop files a ``hydraflow-find`` + ``wiki-rot``
issue through :class:`PRManager` with a fuzzy-match suggestion (via
:func:`difflib.get_close_matches`) when the containing module exists.
After 3 unresolved attempts per ``(slug, cite)`` subject the loop
escalates to ``hitl-escalation`` + ``wiki-rot-stuck``. Dedup keys and
attempt counters clear on escalation close per spec §3.2.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="wiki_rot_detector"``
— **no ``wiki_rot_detector_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from base_background_loop import BaseBackgroundLoop, LoopDeps
from escalation_reconcile import EscalationReconciler
from exception_classify import reraise_on_credit_or_bug
from models import WorkCycleResult
from wiki_rot_citations import (
    Cite,
    ShippedClaim,
    extract_cites,
    extract_fenced_hints,
    extract_shipped_claims,
    fuzzy_suggest,
    verify_cite_ast,
    verify_cite_grep,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from repo_wiki import RepoWikiStore
    from state import StateTracker

logger = logging.getLogger("hydraflow.wiki_rot_detector_loop")


class _TickResult(TypedDict):
    """Per-repo scan result — counts plus the live broken-cite subjects."""

    filed: int
    escalated: int
    broken_subjects: set[str]


_MAX_ATTEMPTS = 3
_EXCERPT_CHARS = 500
_ISSUE_LABELS_FIND: tuple[str, ...] = ("hydraflow-find", "wiki-rot")
_ISSUE_LABELS_ESCALATE: tuple[str, ...] = ("hitl-escalation", "wiki-rot-stuck")


class WikiRotDetectorLoop(BaseBackgroundLoop):
    """Detects broken code cites in per-repo wikis (spec §4.9)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="wiki_rot_detector",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._wiki = wiki_store
        # Open-escalation re-verify (Fix B). The richer (title+body) parser
        # stays on the closed path below; the title-only wrapper covers the
        # standard escalation format, which is all reconcile_open sees.
        self._escalations = EscalationReconciler(
            prs=pr_manager,
            dedup=dedup,
            key_prefix="wiki_rot_detector",
            stuck_label="wiki-rot-stuck",
            clear_attempts=state.clear_wiki_rot_attempts,
            subject_from_title=lambda title: _parse_escalation_subject(title, ""),
        )

    def _get_default_interval(self) -> int:
        return self._config.wiki_rot_detector_interval

    # -- main tick ---------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Scan every repo wiki, file an issue per broken cite, escalate
        repeat offenders.  Guarded by the kill-switch at the top so a
        mid-tick flip takes effect on the next cycle.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.wiki_rot_detector_loop_enabled:
            return {"status": "config_disabled"}

        import time  # noqa: PLC0415

        t0 = time.perf_counter()

        await self._reconcile_closed_escalations()

        self_slug = self._config.repo or ""
        repos = list(self._wiki.list_repos())
        if repos and self_slug and self_slug not in repos:
            # Ensure we always scan HydraFlow-self when the wiki has at
            # least one seeded repo (cite extraction yields 0 otherwise).
            repos.insert(0, self_slug)

        scanned = 0
        filed = 0
        escalated = 0
        any_failed = False
        active_subjects: set[str] = set()
        for slug in repos:
            try:
                result = await self._tick_repo(slug, self_slug)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.exception("wiki_rot_detector: slug=%s failed", slug)
                any_failed = True
                continue
            scanned += 1
            filed += result["filed"]
            escalated += result["escalated"]
            active_subjects |= result["broken_subjects"]

        # Open-escalation re-verify: cites fixed by later changes auto-close
        # their stuck escalations instead of waiting for a human. Skipped on
        # a partial scan (a failed repo's subjects would look "gone") and
        # when nothing was scanned.
        autoclosed = await self._escalations.reconcile_open(
            None if (any_failed or not repos) else active_subjects
        )

        status = "fired" if filed or escalated else "noop"
        self._emit_trace(t0, scanned=scanned, filed=filed, escalated=escalated)
        return {
            "status": status,
            "repos_scanned": scanned,
            "issues_filed": filed,
            "escalations": escalated,
            "autoclosed": autoclosed,
        }

    def _emit_trace(
        self,
        t0: float,
        *,
        scanned: int,
        filed: int,
        escalated: int,
    ) -> None:
        """Best-effort subprocess trace via lazy-imported ``trace_collector``.

        Uses the module's real signature
        ``(loop, command, exit_code, duration_ms, stderr_excerpt)``.
        Import failure, missing attr, or an emit exception all no-op —
        tick telemetry never fails the loop (§12.2 sibling lock).
        """
        import time  # noqa: PLC0415

        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        if emit_loop_subprocess_trace is None:  # patched to None in tests
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        try:
            emit_loop_subprocess_trace(
                loop=self._worker_name,
                command=[
                    "PRPort.list_closed_issues_by_label",
                    "wiki-rot-stuck",
                    "limit=50",
                ],
                exit_code=0,
                duration_ms=duration_ms,
                stderr_excerpt=(
                    f"scanned={scanned} filed={filed} escalated={escalated}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug("trace emission failed", exc_info=True)

    async def _tick_repo(
        self,
        slug: str,
        self_slug: str,
    ) -> _TickResult:
        """Scan one repo's wiki entries, verify cites, file issues, and
        escalate repeat offenders.

        Returns ``{"filed": n, "escalated": n, "broken_subjects": set}``
        where ``broken_subjects`` holds every ``{slug}:{cite}`` found broken
        this tick — INCLUDING dedup-suppressed ones (already filed, still
        broken), which drive open-escalation re-verification. Failures on
        a single entry are logged and skipped — the tick never aborts
        mid-repo.
        """
        filed = 0
        escalated = 0
        broken_subjects: set[str] = set()

        entries = self._load_wiki_entries(slug)
        if not entries:
            return {"filed": 0, "escalated": 0, "broken_subjects": set()}

        is_self = slug == self_slug and bool(self_slug)
        repo_root = Path(self._config.repo_root)
        dedup_seen = self._dedup.get()

        for title, body, entry_path in entries:
            cites = extract_cites(body)
            hints = extract_fenced_hints(body)

            # Shipped-claim pass (issue #9598): structured ``fixed_in_pr``
            # claims are corroborated against their own code_refs. Refs of an
            # *uncorroborated* claim are suppressed from the per-cite pass so a
            # stale shipped claim yields ONE entry-level finding (naming the
            # PR + revert/rename remediation) instead of N per-cite findings.
            # Self-repo only — corroboration needs AST over checked-out source.
            uncorroborated: list[ShippedClaim] = []
            suppressed_refs: set[str] = set()
            if is_self:
                for claim in extract_shipped_claims(body):
                    if self._shipped_claim_corroborated(claim, repo_root):
                        continue
                    uncorroborated.append(claim)
                    suppressed_refs.update(claim.code_refs)

            for cite in cites:
                if cite.raw in suppressed_refs:
                    continue  # covered by the shipped-claim finding below
                broken, suggestion = self._check_cite(cite, repo_root, is_self)
                if not broken:
                    continue
                subject = f"{slug}:{cite.raw}"
                # Counted BEFORE the dedup guard — a dedup-suppressed cite
                # is still broken and must keep its escalation alive.
                broken_subjects.add(subject)
                dedup_key = f"wiki_rot_detector:{subject}"
                if dedup_key in dedup_seen:
                    continue

                filed += 1
                await self._file_find(
                    slug=slug,
                    entry_title=title,
                    entry_path=str(entry_path),
                    body=body,
                    cite=cite,
                    suggestion=suggestion,
                    hints=hints,
                )
                dedup_seen.add(dedup_key)

                attempts = self._state.inc_wiki_rot_attempts(subject)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(
                        slug=slug,
                        cite=cite,
                        attempts=attempts,
                    )
                    escalated += 1

            for claim in uncorroborated:
                subject = f"{slug}:shipped {claim.pr_ref}"
                # Counted before the dedup guard so a live-but-filed claim
                # keeps its escalation alive (mirrors the per-cite path).
                broken_subjects.add(subject)
                dedup_key = f"wiki_rot_detector:{subject}"
                if dedup_key in dedup_seen:
                    continue

                filed += 1
                await self._file_shipped_find(
                    slug=slug,
                    entry_title=title,
                    entry_path=str(entry_path),
                    body=body,
                    claim=claim,
                )
                dedup_seen.add(dedup_key)

                attempts = self._state.inc_wiki_rot_attempts(subject)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_shipped_escalation(
                        slug=slug,
                        claim=claim,
                        attempts=attempts,
                    )
                    escalated += 1

        self._dedup.set_all(dedup_seen)
        return {
            "filed": filed,
            "escalated": escalated,
            "broken_subjects": broken_subjects,
        }

    # -- helpers -----------------------------------------------------------

    def _load_wiki_entries(
        self,
        slug: str,
    ) -> list[tuple[str, str, Path]]:
        """Return ``[(title, body, path), ...]`` for every markdown entry
        in the repo's wiki — supports both the legacy topic-file layout
        and the Phase 3 per-entry layout.  Title defaults to the file
        stem when no ``# Heading`` is present.
        """
        try:
            repo_dir = self._wiki.repo_dir(slug)
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug("wiki.repo_dir(%s) failed", slug, exc_info=True)
            return []
        if not repo_dir.is_dir():
            return []

        out: list[tuple[str, str, Path]] = []
        for md_path in sorted(repo_dir.rglob("*.md")):
            if md_path.name in {"index.md", "log.md"}:
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = _first_heading(text) or md_path.stem
            out.append((title, text, md_path))
        return out

    def _check_cite(
        self,
        cite: Cite,
        repo_root: Path,
        is_self: bool,
    ) -> tuple[bool, str | None]:
        """Verify *cite* and emit a fuzzy suggestion when plausible.

        Returns ``(broken, suggestion)``.  ``broken`` is ``True`` when
        the cite does not resolve; ``suggestion`` is a close-match
        symbol name from the same module, or ``None`` when no close
        match exists / the module itself is missing.
        """
        if cite.style == "fenced_hint":
            return (False, None)  # hints never trigger fires

        module_path = cite.module_as_path()

        if is_self:
            ok, symbols = verify_cite_ast(repo_root, module_path, cite.symbol)
            if ok:
                return (False, None)
            suggestion: str | None = None
            if symbols:
                # Prefer a fuzzy close-match; fall back to the first
                # defined symbol so operators always have *some* anchor
                # pointing into the real module.
                suggestion = fuzzy_suggest(cite.symbol, symbols) or symbols[0]
            return (True, suggestion)

        # Managed repo — grep wiki markdown mirrors only (AST verification
        # against unchecked-out managed-repo sources is out of scope v1).
        ok = verify_cite_grep(repo_root, module_path, cite.symbol)
        return (not ok, None)

    def _shipped_claim_corroborated(
        self,
        claim: ShippedClaim,
        repo_root: Path,
    ) -> bool:
        """Return ``True`` iff *claim* is backed by live code.

        A ``fixed_in_pr`` claim is corroborated when at least one of its
        ``code_refs`` resolves against the checked-out source — a
        ``path.py:symbol`` ref via AST (with a grep fallback for
        re-exports / non-Python targets), or a bare file ref by existence.
        A claim with **no** ``code_refs`` is unverifiable offline and
        therefore uncorroborated — the PR-merge-state network check that
        would settle it is the split-out follow-up (#9664); auto-memory
        notes outside the repo are out of scope for CI (#9935).
        """
        if not claim.code_refs:
            return False
        for ref in claim.code_refs:
            module_path, sep, symbol = ref.partition(":")
            if sep and symbol:
                ok, _ = verify_cite_ast(repo_root, module_path, symbol)
                if ok or verify_cite_grep(repo_root, module_path, symbol):
                    return True
            elif (repo_root / module_path).is_file():
                return True
        return False

    async def _file_find(
        self,
        *,
        slug: str,
        entry_title: str,
        entry_path: str,
        body: str,
        cite: Cite,
        suggestion: str | None,
        hints: list[Cite],
    ) -> None:
        title = f"Wiki rot: {entry_title} cites missing {cite.raw}"
        excerpt = _excerpt_around(body, cite.raw, _EXCERPT_CHARS)
        lines: list[str] = [
            "**Automated detection — WikiRotDetectorLoop (spec §4.9).**",
            "",
            f"- Repo: `{slug}`",
            f"- Entry: `{entry_path}` — *{entry_title}*",
            f"- Broken cite: `{cite.raw}` ({cite.style})",
        ]
        if suggestion:
            lines.append(f"- Did you mean: {suggestion}?")
        if hints:
            hint_names = ", ".join(sorted({h.symbol for h in hints})[:10])
            lines.append(f"- Fenced-code hints (context only): {hint_names}")
        lines += [
            "",
            "### Entry excerpt",
            "",
            "```markdown",
            excerpt,
            "```",
            "",
            "Repair path: implementer updates the cite or removes the "
            "stale entry; the caretaker wiki loop compiles the patch "
            "through the standard review + auto-merge flow.",
        ]
        body_out = "\n".join(lines)
        await self._pr.create_issue(
            title,
            body_out,
            list(_ISSUE_LABELS_FIND),
        )

    async def _file_escalation(
        self,
        *,
        slug: str,
        cite: Cite,
        attempts: int,
    ) -> None:
        title = f"Wiki rot stuck: {slug} cites missing {cite.raw}"
        body = (
            "**Escalation — WikiRotDetectorLoop (spec §4.9 / §3.2).**\n\n"
            f"- Repo: `{slug}`\n"
            f"- Broken cite: `{cite.raw}`\n"
            f"- Attempts: `{attempts}` ≥ `{_MAX_ATTEMPTS}` — repair loop "
            "has not closed the finding within the retry budget.\n\n"
            "Human: resolve the cite or remove the wiki entry, then "
            "close this issue. The dedup key + attempt counter clear "
            "automatically on close (spec §3.2).\n"
        )
        await self._pr.create_issue(
            title,
            body,
            list(_ISSUE_LABELS_ESCALATE),
        )

    async def _file_shipped_find(
        self,
        *,
        slug: str,
        entry_title: str,
        entry_path: str,
        body: str,
        claim: ShippedClaim,
    ) -> None:
        """File a finding for an uncorroborated ``fixed_in_pr`` claim.

        The entry asserts a fix shipped in ``claim.pr_ref`` but none of its
        ``code_refs`` resolve at HEAD — the #9455-shape drift: a "shipped"
        claim with no surviving code. Remediation covers both readings
        (symbol renamed → update code_refs; reverted / never merged →
        verify the PR and remove the entry).
        """
        title = f"Wiki rot: {entry_title} shipped claim {claim.pr_ref} lacks live code"
        excerpt = _excerpt_around(body, claim.pr_ref, _EXCERPT_CHARS)
        refs = ", ".join(f"`{r}`" for r in claim.code_refs) or "(none provided)"
        lines = [
            "**Automated detection — WikiRotDetectorLoop shipped-claim pass "
            "(spec §4.9 / issue #9598).**",
            "",
            f"- Repo: `{slug}`",
            f"- Entry: `{entry_path}` — *{entry_title}*",
            f"- Shipped claim: `fixed_in_pr = {claim.pr_ref}`",
            f"- Code references that no longer resolve: {refs}",
            "",
            "This entry claims a fix shipped in "
            f"{claim.pr_ref}, but none of its code references exist at HEAD. "
            "Either the symbols were renamed (update `code_refs`), or the fix "
            "was reverted / the PR never merged with content (verify "
            f"{claim.pr_ref} merged, then correct or remove the entry).",
            "",
            "### Entry excerpt",
            "",
            "```markdown",
            excerpt,
            "```",
        ]
        await self._pr.create_issue(
            title,
            "\n".join(lines),
            list(_ISSUE_LABELS_FIND),
        )

    async def _file_shipped_escalation(
        self,
        *,
        slug: str,
        claim: ShippedClaim,
        attempts: int,
    ) -> None:
        """Escalate a repeatedly-unresolved shipped claim.

        The title mirrors the per-cite escalation grammar
        (``... cites missing shipped {pr_ref}``) so the existing
        :func:`_parse_escalation_subject` reconciler clears its dedup key +
        attempt counter on close without any parser change.
        """
        title = f"Wiki rot stuck: {slug} cites missing shipped {claim.pr_ref}"
        body = (
            "**Escalation — WikiRotDetectorLoop shipped-claim pass "
            "(spec §4.9 / §3.2 / issue #9598).**\n\n"
            f"- Repo: `{slug}`\n"
            f"- Shipped claim: `fixed_in_pr = {claim.pr_ref}` — uncorroborated "
            "by any live code reference.\n"
            f"- Attempts: `{attempts}` ≥ `{_MAX_ATTEMPTS}` — repair loop "
            "has not closed the finding within the retry budget.\n\n"
            f"Human: verify {claim.pr_ref} merged and fix the code references, "
            "or remove the stale entry, then close this issue. The dedup key "
            "+ attempt counter clear automatically on close (spec §3.2).\n"
        )
        await self._pr.create_issue(
            title,
            body,
            list(_ISSUE_LABELS_ESCALATE),
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Poll closed ``wiki-rot-stuck`` escalations and clear the
        matching dedup key + attempt counter.  Called at the top of
        every tick; close-to-clear latency is bounded by the loop
        interval (spec §3.2).
        """
        try:
            closed = await self._pr.list_closed_issues_by_label(
                "wiki-rot-stuck", limit=50
            )
        except Exception as exc:  # noqa: BLE001
            reraise_on_credit_or_bug(exc)
            logger.debug("reconcile: gh list failed", exc_info=True)
            return

        if not closed:
            return

        current = self._dedup.get()
        to_clear: set[str] = set()
        for issue in closed:
            subject = _parse_escalation_subject(
                str(issue.get("title", "")),
                str(issue.get("body", "")),
            )
            if subject is None:
                continue
            key = f"wiki_rot_detector:{subject}"
            if key in current:
                to_clear.add(key)
            self._state.clear_wiki_rot_attempts(subject)

        if to_clear:
            remaining = current - to_clear
            self._dedup.set_all(remaining)


# -- module helpers --------------------------------------------------------


def _parse_escalation_subject(title: str, body: str) -> str | None:
    """Extract ``{slug}:{cite}`` from an escalation issue.

    Title format: ``Wiki rot stuck: {slug} cites missing {cite}``.
    ``{slug}`` is parsed directly from the title (everything between
    ``stuck: `` and `` cites missing ``); falls back to a ``Repo: `` line
    in the body on malformed titles.
    """
    prefix = "Wiki rot stuck: "
    anchor = " cites missing "
    if not title.startswith(prefix) or anchor not in title:
        return None
    slug_plus_tail = title[len(prefix) :]
    slug, _, cite = slug_plus_tail.partition(anchor)
    slug = slug.strip()
    cite = cite.strip()
    if not slug or not cite:
        # Fallback: ``Repo: `slug`` in body.
        for line in body.splitlines():
            if line.strip().startswith("- Repo:") or line.strip().startswith("Repo:"):
                slug = line.split("`")[1] if "`" in line else slug
                break
    if not slug or not cite:
        return None
    return f"{slug}:{cite}"


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def _excerpt_around(body: str, needle: str, limit: int) -> str:
    """Return a ≤*limit*-char window centered on *needle* — or the head
    of *body* if *needle* is near the top / absent.
    """
    if len(body) <= limit:
        return body
    idx = body.find(needle)
    if idx < 0:
        return body[:limit]
    start = max(0, idx - limit // 2)
    end = min(len(body), start + limit)
    return body[start:end]
