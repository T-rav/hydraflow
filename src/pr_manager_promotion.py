"""Promotion / RC branch lifecycle slice of :class:`pr_manager.PRManager`.

Extracted verbatim from ``pr_manager.py`` (god-file decomposition, #10840
concentration work): the ADR-0042 two-tier release-promotion sub-workflow —
RC branch cut, promotion PR open/find/merge, synthetic-commit workaround,
branch protection, RC retention listing, and the branch-update recovery
helpers it shares with the squash path.

``PRManager`` inherits :class:`PRManagerPromotionMixin`, so every method here
is still reachable exactly as before (``PRManager().merge_promotion_pr`` etc.)
and ``from pr_manager import PRManager`` callers are unaffected. The mixin is
not intended for standalone use — it declares the host seams it needs as
stubs, all provided by ``PRManager``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from models import MergeUpdatePayload, PRCreatedPayload, PRInfo
from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from events import EventBus

# Same channel as pr_manager — the promotion slice is still PRManager
# behavior; keeping one logger name preserves existing log filtering.
logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerPromotionMixin:
    """RC promotion sub-workflow mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Host seams — attributes and helpers provided by PRManager.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _bus: EventBus
    _credentials: Credentials

    def _assert_repo(self) -> None: ...  # provided by PRManager

    async def _run_gh(
        self, *cmd: str, cwd: Path | None = None
    ) -> str: ...  # provided by PRManager

    async def _run_with_body_file(
        self,
        *cmd: str,
        body: str,
        cwd: Path | None = None,
        file_flag: str = "--body-file",
    ) -> str: ...  # provided by PRManager

    async def wait_for_ci(
        self,
        pr_number: int,
        timeout: int,
        poll_interval: int,
        stop_event: asyncio.Event,
    ) -> tuple[bool, str]: ...  # provided by PRManager

    # ------------------------------------------------------------------
    # Promotion / RC lifecycle (moved verbatim from pr_manager.py)
    # ------------------------------------------------------------------

    async def create_promotion_pr(
        self,
        *,
        rc_branch: str,
        title: str,
        body: str,
    ) -> int:
        """Open a promotion PR from *rc_branch* into ``main_branch``.

        Used exclusively by :class:`StagingPromotionLoop`. Always targets
        ``main_branch`` regardless of ``staging_enabled`` — this is the path
        that promotes release candidates into the known-good branch.

        Publishes a :data:`EventType.PR_CREATED` event with ``issue=0`` since
        promotion PRs are not tied to a specific issue.
        """
        self._assert_repo()

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create promotion PR from %s to %s",
                rc_branch,
                self._config.main_branch,
            )
            return 0

        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            self._repo,
            "--head",
            rc_branch,
            "--base",
            self._config.main_branch,
            "--title",
            title,
        ]
        output = await self._run_with_body_file(
            *cmd, body=body, cwd=self._config.repo_root
        )
        url = output.strip()
        if "/pull/" not in url:
            raise RuntimeError(
                f"Unexpected gh pr create output (expected PR URL): {url[:200]}"
            )
        pr_number = int(url.rstrip("/").split("/")[-1])

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data=PRCreatedPayload(
                    pr=pr_number,
                    issue=0,
                    branch=rc_branch,
                    draft=False,
                    url=url,
                    title=title,
                ),
            )
        )

        return pr_number

    async def create_rc_branch(self, rc_branch: str) -> str:
        """Create *rc_branch* at the current tip of ``staging_branch``.

        Used exclusively by :class:`StagingPromotionLoop`. Returns the SHA
        the new ref points at. Raises ``RuntimeError`` when the GitHub API
        rejects the create (e.g., the ref already exists).
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create %s from %s",
                rc_branch,
                self._config.staging_branch,
            )
            return "dry-run-sha"

        staging_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{self._config.staging_branch}",
            "--jq",
            ".object.sha",
        )
        sha = staging_raw.strip().strip('"')
        if not sha:
            raise RuntimeError(
                f"Could not resolve {self._config.staging_branch} HEAD sha"
            )

        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs",
            "--method",
            "POST",
            "--field",
            f"ref=refs/heads/{rc_branch}",
            "--field",
            f"sha={sha}",
        )
        return sha

    async def push_synthetic_commit(self, branch: str, message: str) -> str:
        """Append a tree-identical synthetic commit on top of *branch*.

        Workaround for issue #8705: rc/* branches created via the git/refs
        REST API and turned into PRs by ``gh pr create`` don't fire
        ``pull_request: opened`` workflows reliably (CodeQL, Browser
        Scenarios, etc. never run on the PR head SHA). Pushing a
        synthetic commit fires ``pull_request: synchronize`` which DOES
        trigger workflows. The commit's tree is identical to its parent
        so no real changes are introduced.

        Returns the new HEAD SHA.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would push synthetic commit on %s: %s", branch, message
            )
            return "dry-run-sha"
        self._assert_repo()

        head_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{branch}",
            "--jq",
            ".object.sha",
        )
        head_sha = head_raw.strip().strip('"')
        if not head_sha:
            raise RuntimeError(f"Could not resolve {branch} HEAD sha")

        tree_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/commits/{head_sha}",
            "--jq",
            ".tree.sha",
        )
        tree_sha = tree_raw.strip().strip('"')
        if not tree_sha:
            raise RuntimeError(f"Could not resolve tree sha for {head_sha}")

        new_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/commits",
            "--method",
            "POST",
            "--field",
            f"message={message}",
            "--field",
            f"tree={tree_sha}",
            "--raw-field",
            f"parents[]={head_sha}",
        )
        try:
            new_commit = json.loads(new_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Unexpected synthetic-commit POST response: {new_raw[:200]}"
            ) from exc
        new_sha = str(new_commit.get("sha", "")).strip()
        if not new_sha:
            raise RuntimeError(
                f"Synthetic commit POST returned no sha: {new_raw[:200]}"
            )

        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{branch}",
            "--method",
            "PATCH",
            "--field",
            f"sha={new_sha}",
        )
        return new_sha

    async def find_open_promotion_pr(self) -> PRInfo | None:
        """Return the open ``rc/*`` promotion PR targeting ``main_branch``, or None.

        Used exclusively by :class:`StagingPromotionLoop`. Only one promotion
        PR is expected at a time; if multiple exist, the first listed wins.
        """
        if self._config.dry_run:
            return None
        prefix = self._config.rc_branch_prefix
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=open",
                "--field",
                f"base={self._config.main_branch}",
                "--field",
                "per_page=100",
                "--jq",
                f'[.[] | select(.head.ref | startswith("{prefix}")) | '
                "{number, url: .html_url, isDraft: .draft, "
                "branch: .head.ref}] | .[0] // empty",
            )
            text = raw.strip()
            if not text:
                return None
            pr_data = json.loads(text)
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.debug("Could not resolve open promotion PR", exc_info=True)
            return None
        return PRInfo(
            number=int(pr_data["number"]),
            issue_number=0,
            branch=str(pr_data.get("branch", "")),
            url=str(pr_data.get("url", "")),
            draft=bool(pr_data.get("isDraft", False)),
        )

    async def ensure_branch_exists(self, branch: str, *, base: str) -> bool:
        """Create *branch* from *base* HEAD if it doesn't already exist.

        Returns ``True`` when the branch was created this call, ``False`` when
        it already existed. Raises :class:`RuntimeError` on API failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would ensure branch %s from %s", branch, base)
            return False
        try:
            await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/git/refs/heads/{branch}",
                "--jq",
                ".ref",
            )
            return False
        except RuntimeError:
            pass

        base_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{base}",
            "--jq",
            ".object.sha",
        )
        sha = base_raw.strip().strip('"')
        if not sha:
            raise RuntimeError(f"Could not resolve {base} HEAD sha")
        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs",
            "--method",
            "POST",
            "--field",
            f"ref=refs/heads/{branch}",
            "--field",
            f"sha={sha}",
        )
        return True

    async def apply_staging_branch_protection(self, branch: str) -> dict[str, Any]:
        """Apply HydraFlow's default protection rules to *branch*.

        Rules: no force-push, no deletion, require CI + Quality status checks
        pass before merge, linear history not required (merge commits allowed).
        Admin enforcement is OFF so the factory can still push via its bot.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would protect branch %s", branch)
            return {"status": "dry-run"}

        payload = {
            "required_status_checks": {
                "strict": False,
                "contexts": ["CI", "Quality"],
            },
            "enforce_admins": False,
            "required_pull_request_reviews": None,
            "restrictions": None,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "required_linear_history": False,
            "required_conversation_resolution": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(payload))
            tmp_path = fh.name
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "PUT",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{self._repo}/branches/{branch}/protection",
                "--input",
                tmp_path,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return {"status": "protected", "branch": branch}

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        """Return recently closed ``rc/*`` promotion PRs.

        Each entry: ``{number, branch, merged, closed_at, url}``. Used for
        RC lifecycle dashboard metrics (throughput + failure rate). Only
        PRs whose ``updated_at`` is within *days* of now are returned.

        #8786 Phase 11: routed through the contracts boundary helper in
        lenient mode against ``GhPromotionPR``. The HydraFlow-defined
        projection (a custom ``--jq``) is part of our public contract
        with downstream callers and benefits from the same drift signal
        as direct ``--json`` invocations.
        """
        if self._config.dry_run:
            return []
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhPromotionPR  # noqa: PLC0415

        prefix = self._config.rc_branch_prefix
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=closed",
                "--field",
                f"base={self._config.main_branch}",
                "--field",
                "per_page=100",
                "--field",
                "sort=updated",
                "--field",
                "direction=desc",
                "--jq",
                (
                    f'[.[] | select(.head.ref | startswith("{prefix}")) '
                    f'| select(.updated_at > "{cutoff}") '
                    "| {number, branch: .head.ref, merged: (.merged_at != null), "
                    "closed_at: .closed_at, url: .html_url}]"
                ),
            )
            text = raw.strip()
            if not text:
                return []
            results = parse_list_with_shape(text, GhPromotionPR)
            return [
                (
                    r.model_instance.model_dump(by_alias=False)
                    if r.model_instance is not None
                    else (r.payload if isinstance(r.payload, dict) else {})
                )
                for r in results
            ]
        except (RuntimeError, ValueError, json.JSONDecodeError):
            logger.debug("Could not list recent promotion PRs", exc_info=True)
            return []

    async def list_rc_branches(self) -> list[tuple[str, str]]:
        """Return ``[(branch_name, committer_date_iso), ...]`` for all ``rc/*`` refs.

        Used exclusively by :class:`StagingPromotionLoop` for retention cleanup.
        ``committer_date`` is the ref tip's committer date (ISO 8601), which
        matches the time the RC was cut since RC branches are frozen snapshots.
        """
        if self._config.dry_run:
            return []
        prefix = self._config.rc_branch_prefix
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/git/matching-refs/heads/{prefix}",
                "--jq",
                "[.[] | {ref: .ref, sha: .object.sha}]",
            )
            refs = json.loads(raw) if raw.strip() else []
        except (RuntimeError, ValueError, json.JSONDecodeError):
            logger.debug("Could not list rc/* refs", exc_info=True)
            return []

        results: list[tuple[str, str]] = []
        for ref in refs:
            branch = str(ref.get("ref", "")).removeprefix("refs/heads/")
            sha = str(ref.get("sha", ""))
            if not branch or not sha:
                continue
            try:
                commit_raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/git/commits/{sha}",
                    "--jq",
                    ".committer.date",
                )
            except RuntimeError:
                logger.debug(
                    "Could not fetch committer date for %s", sha, exc_info=True
                )
                continue
            committer_date = commit_raw.strip().strip('"')
            if committer_date:
                results.append((branch, committer_date))
        return results

    async def delete_branch(self, branch: str) -> bool:
        """Delete *branch* from the remote. Returns True on success."""
        if self._config.dry_run:
            logger.info("[dry-run] Would delete branch %s", branch)
            return True
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "DELETE",
                f"repos/{self._repo}/git/refs/heads/{branch}",
            )
            return True
        except RuntimeError:
            logger.warning("Failed to delete branch %s", branch, exc_info=True)
            return False

    async def update_pr_branch(self, pr_number: int, *, method: str = "rebase") -> bool:
        """Update the PR head onto its target branch via GitHub's API.

        Wraps ``PUT /repos/{owner}/{repo}/pulls/{n}/update-branch`` with
        ``update_method=<method>``. *method* is ``"rebase"`` (rewrites the head
        SHAs onto target) or ``"merge"`` (SHA-preserving — merges target into the
        head; GitHub's own default). :meth:`merge_promotion_pr` recovery uses
        ``"merge"`` so RC SHAs survive and ``main`` stays an ancestor of
        ``staging`` (#10552); the squash-based :meth:`merge_pr` recovery uses the
        ``"rebase"`` default. Returns True when GitHub successfully updates the
        head ref (HTTP 202), False on conflict (HTTP 422) or any other failure.
        The factory's "process-driven merge" pattern uses this to recover when
        ``merge_pr`` / ``merge_promotion_pr`` fail because the head fell behind
        target.

        Real conflicts (overlap that GitHub can't auto-resolve) surface as
        False; callers fall through to their existing failure paths (find-issue,
        HITL release) — we never auto-resolve conflict markers locally.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would update branch on PR #%d via %s", pr_number, method
            )
            return True
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "PUT",
                f"repos/{self._repo}/pulls/{pr_number}/update-branch",
                "--field",
                f"update_method={method}",
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "update_pr_branch(#%d, method=%s) failed: %s", pr_number, method, exc
            )
            return False

    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Retarget a PR's base branch via `gh pr edit --base`.

        Used by ``BaseBranchAutoRetargeter`` to retarget PRs opened against
        the wrong base after the two-tier branch model is activated. Idempotent
        from GitHub's side (re-targeting to the same base is a no-op).

        Returns True on success, False on failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would update PR #%d base to %s", pr_number, base)
            return True
        try:
            await run_subprocess(
                "gh",
                "pr",
                "edit",
                str(pr_number),
                "--repo",
                self._repo,
                "--base",
                base,
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "update_pr_base(#%d, base=%s) failed: %s", pr_number, base, exc
            )
            return False

    async def _rebase_and_recheck_ci(
        self,
        pr_number: int,
        *,
        method: str = "rebase",
        ci_timeout: int = 300,
        ci_poll_interval: int = 30,
    ) -> bool:
        """Update the PR head onto its target via *method* and re-poll CI.

        *method* selects GitHub's ``update_method``: ``"rebase"`` (default, used
        by the squash-based :meth:`merge_pr` recovery — squash discards pre-merge
        SHAs anyway) or ``"merge"`` (used by :meth:`merge_promotion_pr` recovery,
        which MUST preserve the RC commit SHAs so ``main`` stays an ancestor of
        ``staging`` — see #10552).

        Returns True only when both the update and post-update CI succeed (caller
        should retry merge). False = give up: the update hit a real conflict, or
        post-update CI failed."""
        if not await self.update_pr_branch(pr_number, method=method):
            return False
        # Fresh stop_event: this is a one-shot recovery, not bound to the
        # caller's loop lifecycle.
        passed, _summary = await self.wait_for_ci(
            pr_number, ci_timeout, ci_poll_interval, asyncio.Event()
        )
        return passed

    async def merge_promotion_pr(
        self, pr_number: int, *, auto_rebase: bool = False
    ) -> bool:
        """Merge *pr_number* via ``--merge`` (merge commit), not squash.

        Used exclusively by :class:`StagingPromotionLoop`. Merge commit
        preserves the staging integration history on ``main`` and avoids
        the growing-diff problem a squash-merged promotion PR would create
        on the next RC cycle. See ADR-0042.

        When ``auto_rebase=True`` and the merge fails (the RC head is behind
        ``main`` by the main-only synthetic ``chore(rc)`` + merge commits),
        attempts one recovery cycle before giving up: update the RC branch onto
        ``main`` via ``update_method=merge`` — SHA-preserving, so ``main`` stays
        an ancestor of ``staging`` — then re-poll CI and retry the merge. A
        rebase-update here would rewrite every RC SHA and permanently diverge
        ``main`` from ``staging`` (see #10552).
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would promotion-merge PR #%d", pr_number)
            return True
        for attempt in range(2):
            try:
                await run_subprocess(
                    "gh",
                    "pr",
                    "merge",
                    str(pr_number),
                    "--repo",
                    self._repo,
                    "--merge",
                    "--delete-branch",
                    cwd=self._config.repo_root,
                    gh_token=self._credentials.gh_token,
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.MERGE_UPDATE,
                        data=MergeUpdatePayload(pr=pr_number, status="merged"),
                    )
                )
                return True
            except RuntimeError as exc:
                logger.warning(
                    "Promotion merge failed for PR #%d (attempt %d): %s",
                    pr_number,
                    attempt + 1,
                    exc,
                )
                if (
                    attempt == 0
                    and auto_rebase
                    and await self._rebase_and_recheck_ci(pr_number, method="merge")
                ):
                    continue
                return False
        return False
