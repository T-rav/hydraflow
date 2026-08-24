"""``EpicCompletionChecker`` — auto-close and release creation for a parent
epic once its sub-issues finish.

A separate collaborator, not a slice of ``EpicManager``: it is constructed
independently (``service_registry``, ``post_merge_handler``) and it owns
the only call to ``generate_changelog`` in the module. ADR-0011 pins that
the epic-close entry point must NOT call the release primitive; keeping
both halves in one file is what makes that reviewable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from changelog import generate_changelog
from config import HydraFlowConfig
from issue_fetcher import IssueFetcher
from models import (
    EpicState,
    GitHubIssueState,
    Release,
)
from pr_manager import PRManager
from state import StateTracker

from ._parse import (
    check_all_checkboxes,
    extract_version_from_title,
    parse_epic_sub_issues,
)

logger = logging.getLogger("hydraflow.epic")


class EpicCompletionChecker:
    """Checks whether parent epics should be auto-closed after sub-issue completion."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        fetcher: IssueFetcher,
        state: StateTracker | None = None,
    ) -> None:
        self._config = config
        self._prs = prs
        self._fetcher = fetcher
        self._state = state
        self._active_closings: set[int] = set()  # recursion guard for nested epics

    async def check_and_close_epics(self, completed_issue_number: int) -> bool:
        """Check all open epics and close any whose sub-issues are all completed.

        Returns True if at least one epic was successfully closed.
        """
        try:
            epics = await self._fetcher.fetch_issues_by_labels(
                self._config.epic_label, limit=50
            )
        except RuntimeError:
            logger.warning(
                "Failed to fetch epic issues for completion check",
                exc_info=True,
            )
            return False

        closed_any = False
        for epic in epics:
            sub_issues = parse_epic_sub_issues(epic.body)
            if not sub_issues:
                continue
            if completed_issue_number not in sub_issues:
                continue

            try:
                closed = await self._try_close_epic(
                    epic.number, epic.title, epic.body, sub_issues
                )
                if closed:
                    closed_any = True
            except RuntimeError:
                logger.warning(
                    "Epic completion check failed for epic #%d",
                    epic.number,
                    exc_info=True,
                )
        return closed_any

    async def _try_close_epic(
        self, epic_number: int, epic_title: str, epic_body: str, sub_issues: list[int]
    ) -> bool:
        """Close the epic if all sub-issues are resolved (fixed, closed, or excluded).

        A sub-issue is considered resolved if it:
        - Has the ``fixed_label`` (completed normally)
        - Is a nested epic that is itself closed
        - Is closed without the fixed_label (wontfix/duplicate/invalid)

        Sub-issues with the HITL label that are still open produce a warning
        comment and DO temporarily block epic completion until resolved.

        After closing, triggers a parent-epic re-check so that nested epic
        closure propagates upward automatically.

        Returns True if the epic was closed, False otherwise.
        """
        # Recursion guard: the membership test + add are synchronous (no
        # await between them), so no other coroutine can interleave here.
        if epic_number in self._active_closings:
            return False
        self._active_closings.add(epic_number)

        try:
            return await self._do_close_epic(
                epic_number, epic_title, epic_body, sub_issues
            )
        finally:
            self._active_closings.discard(epic_number)

    async def _do_close_epic(
        self, epic_number: int, epic_title: str, epic_body: str, sub_issues: list[int]
    ) -> bool:
        """Inner close logic — separated to allow recursion guard in _try_close_epic."""
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""
        hitl_labels = set(self._config.hitl_label)
        epic_labels = set(self._config.epic_label)

        # Track sub-issue list changes for audit trail
        self._audit_sub_issue_changes(epic_number, sub_issues)

        sub_issue_titles: list[str] = []
        excluded_issues: list[int] = []
        hitl_blocked: list[int] = []
        for issue_number in sub_issues:
            issue = await self._fetcher.fetch_issue_by_number(issue_number)
            if issue is None:
                logger.warning(
                    "Sub-issue #%d not found while checking epic #%d — skipping",
                    issue_number,
                    epic_number,
                )
                return False

            issue_labels = set(issue.labels)
            is_fixed = bool(fixed_label) and fixed_label in issue_labels
            is_closed_nested_epic = (
                bool(epic_labels & issue_labels)
                and issue.state == GitHubIssueState.CLOSED
            )
            if is_fixed or is_closed_nested_epic:
                sub_issue_titles.append(issue.title)
                continue

            if issue.state == GitHubIssueState.CLOSED:
                # #9757 defense-in-depth: a decomposed child is closed the moment
                # its replacement epic is created, but its work lives on there.
                # Don't treat it as resolved until that replacement epic's GitHub
                # issue closes — the same gate EpicSweeperLoop applies. This path
                # (checker) is dormant when EpicManager is wired, but gating it
                # keeps the nested-convergence invariant for any future caller.
                replacement = (
                    self._state.get_replacement_epic(issue_number)
                    if self._state is not None
                    else None
                )
                if replacement is not None:
                    rep_issue = await self._fetcher.fetch_issue_by_number(
                        replacement.epic_number
                    )
                    if rep_issue is not None and rep_issue.state != (
                        GitHubIssueState.CLOSED
                    ):
                        return False
                excluded_issues.append(issue_number)
                logger.info(
                    "Sub-issue #%d closed without fixed label — treating as excluded "
                    "for epic #%d",
                    issue_number,
                    epic_number,
                )
                continue

            if hitl_labels & issue_labels:
                hitl_blocked.append(issue_number)
                continue

            return False

        # Post HITL warnings if any sub-issues are in HITL
        if hitl_blocked:
            await self._post_hitl_warnings(epic_number, hitl_blocked)
            return False

        # All sub-issues are resolved — close the epic
        logger.info("All sub-issues resolved for epic #%d — closing", epic_number)

        # Persist excluded children in state if available
        if self._state is not None and excluded_issues:
            epic_state = self._state.get_epic_state(epic_number)
            if epic_state is not None:
                for excl in excluded_issues:
                    if excl not in epic_state.excluded_children:
                        epic_state.excluded_children.append(excl)
                self._state.upsert_epic_state(epic_state)

        updated_body = check_all_checkboxes(epic_body)
        await self._prs.update_issue_body(epic_number, updated_body)
        if fixed_label:
            await self._prs.add_labels(epic_number, [fixed_label])

        release_url = ""
        generated_changelog = ""

        close_comment = "All sub-issues resolved — closing epic automatically."
        if excluded_issues:
            excluded_str = ", ".join(f"#{n}" for n in excluded_issues)
            close_comment += f"\n\n**Excluded (closed without merge):** {excluded_str}"
        if release_url:
            close_comment += f"\n\n**Release:** {release_url}"
        await self._prs.post_comment(epic_number, close_comment)
        await self._prs.close_issue(epic_number)

        # Optionally write to CHANGELOG.md file
        if self._config.changelog_file:
            if not generated_changelog:
                extracted_version = extract_version_from_title(epic_title) or None
                generated_changelog = await self._generate_epic_changelog(
                    epic_number, sub_issues, version=extracted_version
                )
            if generated_changelog:
                self._write_changelog_file(generated_changelog)

        # Propagate to parent epics: the just-closed epic may be a sub-issue
        # of another epic. Re-check so parent closure cascades automatically.
        await self.check_and_close_epics(epic_number)

        return True

    async def close_specific_epic(self, epic_number: int) -> bool | None:
        """Check and close a specific epic if all sub-issues are resolved.

        Returns ``True`` if the epic was closed, ``False`` if the epic was
        found but has unresolved sub-issues, or ``None`` if the epic could
        not be located on GitHub (missing label, API failure, etc.).
        """
        try:
            epics = await self._fetcher.fetch_issues_by_labels(
                self._config.epic_label, limit=50
            )
        except RuntimeError:
            logger.warning(
                "Failed to fetch epic issues for specific-epic check",
                exc_info=True,
            )
            return None

        epic = next((e for e in epics if e.number == epic_number), None)
        if epic is None:
            return None

        sub_issues = parse_epic_sub_issues(epic.body)
        if not sub_issues:
            return None

        try:
            return await self._try_close_epic(
                epic.number, epic.title, epic.body, sub_issues
            )
        except RuntimeError:
            logger.warning(
                "Epic close failed for #%d during specific-epic check",
                epic_number,
                exc_info=True,
            )
            return None

    async def _post_hitl_warnings(
        self, epic_number: int, hitl_issues: list[int]
    ) -> None:
        """Post a warning comment for HITL-escalated sub-issues (once per issue)."""
        epic_state: EpicState | None = None
        already_warned: set[int] = set()
        if self._state is not None:
            epic_state = self._state.get_epic_state(epic_number)
            if epic_state is not None:
                already_warned = set(epic_state.hitl_warned_children)

        new_warnings = [n for n in hitl_issues if n not in already_warned]
        if not new_warnings:
            return

        issues_str = ", ".join(f"#{n}" for n in new_warnings)
        try:
            await self._prs.post_comment(
                epic_number,
                f"**Epic completion blocked:** {issues_str} "
                f"{'is' if len(new_warnings) == 1 else 'are'} escalated to HITL.\n"
                f"Resolve the HITL {'issue' if len(new_warnings) == 1 else 'issues'} "
                f"or close {'it' if len(new_warnings) == 1 else 'them'} to unblock the release.\n\n"
                f"---\n*HydraFlow Epic Monitor*",
            )
        except RuntimeError:
            logger.warning(
                "Failed to post HITL warning comment for epic #%d",
                epic_number,
                exc_info=True,
            )
            return

        # Track that we've warned about these issues
        if self._state is not None:
            if epic_state is None:
                epic_state = EpicState(epic_number=epic_number)
            for n in new_warnings:
                if n not in epic_state.hitl_warned_children:
                    epic_state.hitl_warned_children.append(n)
            self._state.upsert_epic_state(epic_state)

    def _audit_sub_issue_changes(
        self, epic_number: int, current_sub_issues: list[int]
    ) -> None:
        """Log when the sub-issue list changes between checks."""
        if self._state is None:
            return
        epic_state = self._state.get_epic_state(epic_number)
        if epic_state is None:
            return
        known = set(epic_state.child_issues)
        current = set(current_sub_issues)
        added = current - known
        removed = known - current
        if added:
            logger.info(
                "Epic #%d: new sub-issues detected: %s",
                epic_number,
                ", ".join(f"#{n}" for n in sorted(added)),
            )
            epic_state.child_issues = list(current)
            epic_state.last_activity = datetime.now(UTC).isoformat()
            self._state.upsert_epic_state(epic_state)
        if removed:
            logger.info(
                "Epic #%d: sub-issues removed from body: %s",
                epic_number,
                ", ".join(f"#{n}" for n in sorted(removed)),
            )
            if not added:
                epic_state.child_issues = list(current)
                epic_state.last_activity = datetime.now(UTC).isoformat()
                self._state.upsert_epic_state(epic_state)

    async def _generate_epic_changelog(
        self, epic_number: int, sub_issues: list[int], version: str | None = None
    ) -> str:
        """Generate a changelog from sub-issue PRs. Returns empty string on failure."""
        try:
            v = version or f"epic-{epic_number}"
            return await generate_changelog(
                pr_manager=self._prs,
                sub_issues=sub_issues,
                version=v,
            )
        except RuntimeError:
            logger.warning(
                "Changelog generation failed for epic #%d",
                epic_number,
                exc_info=True,
            )
            return ""

    def _write_changelog_file(self, content: str) -> None:
        """Append changelog content to the configured changelog file."""
        try:
            changelog_path = Path(self._config.changelog_file)
            if not changelog_path.is_absolute():
                changelog_path = self._config.repo_root / changelog_path

            repo_resolved = self._config.repo_root.resolve()
            path_resolved = changelog_path.resolve()
            if not path_resolved.is_relative_to(repo_resolved):
                logger.warning(
                    "changelog_file %r resolves outside repo_root %r — skipping write",
                    str(changelog_path),
                    str(repo_resolved),
                )
                return

            existing = ""
            if changelog_path.exists():
                existing = changelog_path.read_text(encoding="utf-8")

            if existing.startswith("# "):
                first_nl = existing.index("\n") if "\n" in existing else len(existing)
                rest = existing[first_nl + 1 :].lstrip("\n")
                updated = existing[: first_nl + 1] + "\n" + content + "\n" + rest
            else:
                updated = content + "\n" + existing

            changelog_path.write_text(updated, encoding="utf-8")
            logger.info("Changelog written to %s", changelog_path)
        except OSError:
            logger.warning(
                "Failed to write changelog file",
                exc_info=True,
            )

    async def _create_release_for_epic(
        self,
        epic_number: int,
        epic_title: str,
        sub_issues: list[int],
    ) -> tuple[str, str]:
        """Create a git tag and GitHub Release for a completed epic.

        Returns ``(release_url, changelog)`` on success, ``("", "")`` on failure.
        The caller can reuse the generated changelog to avoid redundant API calls.
        """
        if self._config.release_version_source != "epic_title":
            logger.warning(
                "release_version_source=%r is not yet implemented — falling back to 'epic_title'",
                self._config.release_version_source,
            )

        version = extract_version_from_title(epic_title)
        if not version:
            logger.info(
                "No version found in epic #%d title %r — skipping release",
                epic_number,
                epic_title,
            )
            return "", ""

        tag = f"{self._config.release_tag_prefix}{version}"
        changelog = await self._generate_epic_changelog(
            epic_number, sub_issues, version=version
        )
        release_title = f"Release {tag}"

        # #11517: tag the promoted main SHA (ADR-0042's promotion target —
        # ``main_branch``, NOT ``base_branch()``), resolved fresh at release
        # time. The factory checkout's HEAD is ``staging`` or an agent branch
        # and has not passed the RC gate; if main cannot be resolved, skip
        # the release fail-closed rather than fall back to HEAD.
        main_branch = self._config.main_branch
        main_sha = await self._prs.resolve_remote_branch_sha(main_branch)
        if main_sha is None:
            logger.warning(
                "Could not resolve origin/%s for %s — skipping release "
                "(never tagging the factory checkout HEAD)",
                main_branch,
                tag,
            )
            return "", changelog  # preserve changelog so caller can still write to file

        # Create the git tag on the promoted main SHA
        tag_ok = await self._prs.create_tag(tag, ref=main_sha)
        if not tag_ok:
            logger.warning("Tag creation failed for %s — skipping release", tag)
            return "", changelog  # preserve changelog so caller can still write to file

        # Create the GitHub Release
        release_ok = await self._prs.create_release(tag, release_title, changelog)
        if not release_ok:
            logger.warning("GitHub Release creation failed for %s", tag)
            return "", changelog  # preserve changelog so caller can still write to file

        release_url = f"https://github.com/{self._config.repo}/releases/tag/{tag}"

        # Persist release state if a state tracker is available
        release = Release(
            version=version,
            epic_number=epic_number,
            sub_issues=list(sub_issues),
            status="released",
            released_at=datetime.now(UTC).isoformat(),
            changelog=changelog,
            tag=tag,
        )
        if self._state is not None:
            self._state.upsert_release(release)

        logger.info(
            "Created release %s for epic #%d with %d sub-issues",
            tag,
            epic_number,
            len(sub_issues),
        )
        return release_url, changelog
