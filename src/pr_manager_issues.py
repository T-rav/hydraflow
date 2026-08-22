"""Issue lifecycle surface of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerIssuesMixin`, so ``PRManager().close_issue`` and the
``patch("pr_manager.PRManager.close_issue")`` sites resolve unchanged.

One cohesive concern: the GitHub *issue* surface — create, read (state, body,
labels, timestamps), list (by label, open, closed, all), and the
close/reopen/update mutations. PR-side reads live in
``pr_manager_pr_queries``; label mutation lives in ``pr_manager_labels``;
the drift/audit sweeps that cross both live in ``pr_manager_drift``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from events import EventType, HydraFlowEvent
from models import GitHubIssueSummary, IssueCreatedPayload
from pr_manager_common import _gh_wire_labels, _project_issue_summaries

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerIssuesMixin:
    """Issue lifecycle mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _bus: EventBus

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

        async def _gh_json_query(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...  # provided by PRManager

        async def _run_with_body_file(
            self,
            *cmd: str,
            body: str,
            cwd: Path | None = None,
            file_flag: str = "--body-file",
        ) -> str: ...  # provided by PRManager

        async def _remove_label(
            self, target: Literal["issue", "pr"], number: int, label: str
        ) -> None: ...  # provided by PRManagerLabelsMixin

    async def get_issue_state(self, issue_number: int) -> str:
        """Return the resolved state of a GitHub issue.

        Returns ``'COMPLETED'`` when the issue was closed as resolved,
        ``'OPEN'`` when still open, ``'NOT_PLANNED'`` when closed as
        won't-fix/duplicate/invalid, or ``''`` on error.
        """
        self._assert_repo()
        try:
            output = await self._run_gh(
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                self._repo,
                "--json",
                "state,stateReason",
            )
            data = json.loads(output)
            state = str(data.get("state", "")).upper()
            if state == "CLOSED":
                # stateReason: "COMPLETED" | "NOT_PLANNED" | null
                # Fall back to "" (not "COMPLETED") when stateReason is null so
                # that issues closed before GitHub added stateReason tracking are
                # not incorrectly treated as resolved.
                reason = str(data.get("stateReason") or "").upper()
                return reason
            return state
        except Exception:
            logger.warning(
                "Could not fetch state of issue #%d",
                issue_number,
                exc_info=True,
            )
            return "UNKNOWN"

    async def list_issues_by_label(self, label: str) -> list[GitHubIssueSummary]:
        """Return open issues with the given label as a list of dicts.

        #8786 Phase 8: parses through ``contracts.boundary.parse_list_with_shape``
        in *lenient* mode — validation failures log WARN but the method's
        return type and behaviour are unchanged. Existing callers that
        access ``item["number"]`` etc keep working; shape drift is
        observable in ``server.log`` and via ``LiveCorpusReplayLoop``.
        """
        # Local import keeps the module-load contract identical when
        # the contracts subsystem isn't imported elsewhere yet.
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhIssueListItem  # noqa: PLC0415

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,title,body,updatedAt,labels",
            "--limit",
            "100",
        )
        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        return _project_issue_summaries(results)

    async def list_open_issues(self) -> list[GitHubIssueSummary]:
        """Return ALL open issues (no label filter) as a list of dicts.

        Used by the backlog refinement loop (``IssueRefinementLoop``, #9957) for a
        full-repo sweep. Same contracts-boundary lenient-parse pattern as
        ``list_issues_by_label`` — labels ride along in gh wire shape
        (#9943) since refinement needs to reason about existing labels.
        """
        from contracts.boundary import parse_list_with_shape
        from contracts.shapes import GhIssueListItem

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--json",
            "number,title,body,labels,updatedAt",
            "--limit",
            "500",
        )
        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        summaries = _project_issue_summaries(results)
        if len(summaries) == 500:
            logger.warning(
                "list_open_issues returned exactly 500 rows — backlog may be"
                " truncated; raise the limit"
            )
        return summaries

    async def list_all_issues(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return issues in *state* as raw gh-wire dicts.

        Fields: ``number``, ``title``, ``state``, ``labels``, ``createdAt``,
        ``updatedAt``, ``closedAt`` — the union of what the fitness issue
        fetcher (``service_registry``, state="all") and ``StaleIssueLoop``'s
        stale-scan / backlog-budget reads (state="open") need from one gh
        invocation shape. Propagates read/parse failures rather than
        swallowing them.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,state,labels,createdAt,updatedAt,closedAt",
        )
        return json.loads(output) if output else []

    async def list_open_issue_numbers(self, limit: int = 500) -> list[int]:
        """Return the numbers of ALL open issues (no label filter). #9905.

        Narrow ``--json number`` projection: number is the only field the
        state-prune keep-set needs, and narrow projections skip the
        required-fields shape gate by design.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            str(limit),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_open_issue_numbers: unparseable gh output")
            return []
        numbers: list[int] = []
        for row in rows if isinstance(rows, list) else []:
            number = row.get("number") if isinstance(row, dict) else None
            if isinstance(number, int) and number > 0:
                numbers.append(number)
        return numbers

    async def list_closed_issues_by_label(
        self, label: str, limit: int = 100
    ) -> list[GitHubIssueSummary]:
        """Return closed issues with the given label as a list of dicts.

        #8786 Phase 10: routed through the contracts boundary helper in
        lenient mode — same pattern as ``list_issues_by_label``.

        #9727: projects ``closedAt`` → ``closed_at`` so the
        detector-calibration churn window can key on close time
        (``updated_at`` moves on ANY issue activity).

        #8996: also projects ``labels`` in gh wire shape — the closed
        listing used to be label-free by default (#9943), which meant
        ``escalation_reconcile.is_bot_close`` could never see the bot-close
        marker on a closed row from this method and fell open to "treat as
        human" every time. Threading labels through here is what makes that
        predicate load-bearing rather than dead code.
        """
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhIssueListItem  # noqa: PLC0415

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--label",
            label,
            "--state",
            "closed",
            "--json",
            "number,title,body,updatedAt,closedAt,labels",
            "--limit",
            str(limit),
        )
        from contracts.boundary import field_or  # noqa: PLC0415

        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        return [
            {
                "number": field_or(r, "number", 0),
                "title": field_or(r, "title", ""),
                "body": field_or(r, "body", ""),
                "updated_at": field_or(r, "updated_at", "", dict_key="updatedAt"),
                "closed_at": field_or(r, "closed_at", "", dict_key="closedAt"),
                "labels": _gh_wire_labels(r),
            }
            for r in results
        ]

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return the updated_at timestamp for an issue as ISO string."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self._repo,
            "--json",
            "updatedAt",
            "--jq",
            ".updatedAt",
        )
        return output.strip()

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        """Return the label names carried by a GitHub issue.

        Delegates to ``gh issue view <n> --json labels --jq
        '.labels[].name'`` (newline-separated names). Read failures
        propagate rather than being swallowed so that
        ``WorkspaceGCLoop._issue_has_pipeline_label`` can fail-closed on
        error instead of GC'ing an issue whose labels were merely
        unreadable (#9575).
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self._repo,
            "--json",
            "labels",
            "--jq",
            ".labels[].name",
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def get_issue_body(self, issue_number: int) -> str:
        """Return the body text of a GitHub issue.

        Delegates to ``gh issue view <n> --json body``, mirroring
        :meth:`get_issue_labels`'s fail-closed contract (#9575): read
        failures propagate rather than being swallowed, so
        ``ReportIssueLoop._verify_issue`` sees a raised error rather than
        an empty string mistaken for a genuinely blank body.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self._repo,
            "--json",
            "body",
        )
        data = json.loads(output)
        return str(data.get("body") or "")

    async def close_issue(
        self, issue_number: int, *, reason: str | None = None
    ) -> bool:
        """Close a GitHub issue. Returns False when the gh call failed (#9812).

        *reason* maps to ``gh issue close --reason`` (``"completed"`` |
        ``"not planned"``); ``None`` omits the flag, so gh records its
        default ``stateReason=COMPLETED`` (#10025).
        """
        self._assert_repo()
        if self._config.dry_run:
            return True
        reason_args = ("--reason", reason) if reason else ()
        try:
            await self._run_gh(
                "gh",
                "issue",
                "close",
                str(issue_number),
                "--repo",
                self._repo,
                *reason_args,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not close issue #%d: %s",
                issue_number,
                exc,
            )
            return False
        # Choke point (#10394): a closed issue must never keep an active
        # pipeline-stage label, or a label-scan dispatcher will re-queue
        # already-shipped work. Strip them here so every HydraFlow-initiated
        # close is clean. (GitHub-native ``Closes #N`` auto-closes bypass this
        # method entirely — the LabelDriftWatcherLoop, ADR-0088, is the
        # backstop for those.)
        await self._strip_dispatch_labels(issue_number)
        return True

    async def _strip_dispatch_labels(self, issue_number: int) -> None:
        """Remove any active pipeline-stage labels from *issue_number* (#10394).

        Best-effort: reads the issue's current labels once and removes only
        the intersection with ``dispatchable_stage_labels`` — terminal
        markers (``fixed`` / ``verify``) are preserved so the merge path's
        ``hydraflow-fixed`` end-state is unchanged. A label read/remove
        failure is logged, never raised, so it can never turn a successful
        close into a reported failure (the drift watcher will catch anything
        missed on a later tick).
        """
        dispatch_labels = set(self._config.dispatchable_stage_labels)
        if not dispatch_labels:
            return
        try:
            current = set(await self.get_issue_labels(issue_number))
        except RuntimeError as exc:
            logger.debug(
                "close_issue: could not read labels for #%d to strip stage labels: %s",
                issue_number,
                exc,
            )
            return
        for lbl in sorted(current & dispatch_labels):
            await self._remove_label("issue", issue_number, lbl)

    async def reopen_issue(self, issue_number: int) -> bool:
        """Reopen a closed GitHub issue. Returns False when the gh call failed.

        ``gh issue reopen``. Fail-soft (no raise), matching
        :meth:`close_issue` (#9812). Used by the close-verification controller
        (#10358) to undo a false auto-close.
        """
        self._assert_repo()
        if self._config.dry_run:
            return True
        try:
            await self._run_gh(
                "gh",
                "issue",
                "reopen",
                str(issue_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not reopen issue #%d: %s",
                issue_number,
                exc,
            )
            return False
        return True

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        """Update the body of a GitHub issue using ``--body-file``."""
        self._assert_repo()
        if self._config.dry_run:
            return
        try:
            await self._run_with_body_file(
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                self._repo,
                body=body,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not update body for issue #%d: %s",
                issue_number,
                exc,
            )

    async def get_dependabot_alerts(self, state: str = "open") -> list[dict]:
        """Fetch Dependabot alerts for the repository.

        Returns a list of alert dicts from the GitHub API, or an empty list
        on error or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "api",
            f"repos/{self._repo}/dependabot/alerts?state={state}&per_page=100",
            "--paginate",
            dry_run_return=[],
            dry_run_log="[dry-run] Would fetch Dependabot alerts",
            error_log="Failed to fetch Dependabot alerts",
        )

    async def find_existing_issue(self, title: str) -> int:
        """Search for an open issue with an exact title match.

        Returns the issue number of the first match, or 0 if none found.

        #8786 Phase 15: routed through the contracts boundary helper in
        lenient mode against ``GhIssueListItem``. The ``--json number,title``
        shape is a strict subset; drift in either field surfaces via WARN
        without changing the method's return semantics.
        """
        self._assert_repo()
        if self._config.dry_run:
            return 0
        try:
            raw = await self._run_gh(
                "gh",
                "search",
                "issues",
                "--repo",
                self._repo,
                "--state",
                "open",
                "--match",
                "title",
                "--json",
                "number,title",
                "--limit",
                "5",
                "--",
                title,
                cwd=self._config.repo_root,
            )
            if not raw.strip():
                return 0
            from contracts.boundary import (  # noqa: PLC0415
                field_or,
                parse_list_with_shape,
            )
            from contracts.shapes import GhIssueListItem  # noqa: PLC0415

            results = parse_list_with_shape(raw, GhIssueListItem)
            for r in results:
                if field_or(r, "title", "") == title:
                    return int(field_or(r, "number", 0))
            return 0
        except (RuntimeError, ValueError):
            return 0

    async def _ensure_labels_present(self, labels: list[str]) -> None:
        """Create any of *labels* the repo doesn't already have.

        ``gh issue/pr create --label X`` (and ``--add-label X``) abort the
        WHOLE operation when X doesn't exist, so a caller that files with a
        not-yet-provisioned label silently fails — e.g. the ``health_monitor``
        loop-stall dead-man-switch files with ``loop-stalled``, which
        :meth:`ensure_labels_exist` does not create at boot (it only creates
        the fixed lifecycle set). Provisioning missing labels first means
        labeling never fails on an unknown label.

        Idempotent and non-mutating: labels that already exist are left
        untouched (no colour/description reset). Best-effort — a failure to
        list or create degrades to the pre-existing behaviour rather than
        blocking the caller.
        """
        if self._config.dry_run or not labels:
            return
        try:
            listed = await self._run_gh(
                "gh",
                "label",
                "list",
                "--repo",
                self._repo,
                "--limit",
                "500",
                "--json",
                "name",
                "-q",
                ".[].name",
            )
        except RuntimeError as exc:
            logger.warning("Could not list labels to ensure existence: %s", exc)
            return
        existing = {n.strip().lower() for n in listed.splitlines() if n.strip()}
        for label in labels:
            if label.lower() in existing:
                continue
            try:
                await self._run_gh("gh", "label", "create", label, "--repo", self._repo)
                existing.add(label.lower())
                logger.info("Provisioned missing label %r before use", label)
            except RuntimeError as exc:
                logger.warning("Could not provision label %r: %s", label, exc)

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> int:
        """Create a new GitHub issue. Returns the issue number (0 on failure).

        Callers MUST check for ``0`` before storing or referencing the
        returned value.  Treating ``0`` as a real issue number causes
        downstream ``gh issue comment 0`` / ``gh issue close 0`` calls
        to fail with "Could not resolve to an issue or pull request with
        the number of 0" every cycle.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create issue: %s", title)
            return 0

        existing = await self.find_existing_issue(title)
        if existing:
            logger.info(
                "Skipping duplicate issue creation — #%d already open with title %r",
                existing,
                title,
            )
            return existing

        # Provision any not-yet-existing label so `gh issue create --label X`
        # can't abort on it (e.g. the health_monitor escalation's loop-stalled).
        await self._ensure_labels_present(labels or [])

        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            self._repo,
            "--title",
            title,
        ]
        for label in labels or []:
            cmd.extend(["--label", label])

        try:
            output = await self._run_with_body_file(
                *cmd, body=body, cwd=self._config.repo_root
            )
            # gh issue create prints the issue URL — validate before parsing
            url = output.strip()
            if "/issues/" not in url:
                raise RuntimeError(
                    f"Unexpected gh issue create output (expected issue URL): {url[:200]}"
                )
            issue_number = int(url.rstrip("/").split("/")[-1])

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.ISSUE_CREATED,
                    data=IssueCreatedPayload(
                        number=issue_number,
                        title=title,
                        labels=labels or [],
                    ),
                )
            )
            return issue_number
        except (RuntimeError, ValueError) as exc:
            logger.warning("Issue creation failed for %r: %s", title, exc)
            return 0
