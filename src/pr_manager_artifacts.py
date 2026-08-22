"""Tag / release / screenshot-upload surface of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerArtifactsMixin`, so
``PRManager().upload_screenshot`` resolves unchanged.

One cohesive concern: publishing *binary artifacts and refs* to GitHub —
annotated tags, releases, and the two screenshot-hosting paths (release asset
and gist) the visual gate uses to get a PNG onto a URL a reviewer can open.

Tests that patch the temp-file plumbing of ``upload_screenshot_gist`` target
``pr_manager_artifacts.tempfile`` / ``.os`` now that the call site lives here
— the same target migration ``pr_manager_promotion.run_subprocess`` took in
#10840. ``_run_with_body_file`` (the other ``tempfile`` user) stayed in
``pr_manager.py``, so ``patch("pr_manager.tempfile.mkstemp")`` is unchanged
for that path.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerArtifactsMixin:
    """Tag/release/screenshot publishing mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _SCREENSHOT_RELEASE_TAG: str

    if TYPE_CHECKING:

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

    async def create_tag(self, tag: str, *, ref: str) -> bool:
        """Create a git tag on the explicit *ref* and push it to origin.

        *ref* is keyword-only with no default on purpose (#11517): a release
        tag must name the commit it targets — the promoted ``main`` SHA from
        :meth:`resolve_remote_branch_sha` — never an implicit ``HEAD``, which
        under ADR-0042 is the ``staging`` checkout or an agent branch.

        Returns *True* on success, *False* on failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create tag %s on %s", tag, ref)
            return True
        try:
            await self._run_gh("git", "tag", tag, ref)
            await self._run_gh("git", "push", "origin", tag)
            return True
        except RuntimeError as exc:
            logger.warning("Could not create tag %s: %s", tag, exc)
            return False

    async def create_release(
        self,
        tag: str,
        title: str,
        body: str,
    ) -> bool:
        """Create a GitHub Release for the given *tag*.

        Returns *True* on success, *False* on failure.
        Uses a temp file for the notes body to avoid argument length limits.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create release %s", tag)
            return True

        try:
            await self._run_with_body_file(
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                self._repo,
                "--title",
                title,
                body=body,
                file_flag="--notes-file",
            )
            return True
        except RuntimeError as exc:
            logger.warning("Could not create release %s: %s", tag, exc)
            return False

    async def upload_screenshot(self, png_path: Path) -> str:
        """Upload a local PNG to GitHub as a release asset and return the URL.

        Uses a dedicated ``screenshots`` release tag.  The release is
        created automatically on first use.  Each file is uploaded with
        a unique name (timestamp + original stem) so assets never collide.

        Returns an empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would upload screenshot")
            return ""

        self._assert_repo()

        try:
            await self._ensure_screenshot_release()

            # Unique asset name to avoid collisions (gh uses the filename)
            import shutil
            import time as _time

            ts = int(_time.time())
            asset_name = f"{ts}-{png_path.stem}.png"
            upload_path = png_path.parent / asset_name
            shutil.copy2(png_path, upload_path)

            try:
                await self._run_gh(
                    "gh",
                    "release",
                    "upload",
                    self._SCREENSHOT_RELEASE_TAG,
                    str(upload_path),
                    "--repo",
                    self._repo,
                    "--clobber",
                )
            finally:
                upload_path.unlink(missing_ok=True)

            url = (
                f"https://github.com/{self._repo}/releases/download/"
                f"{self._SCREENSHOT_RELEASE_TAG}/{asset_name}"
            )
            logger.info("Screenshot uploaded: %s", url)
            return url
        except Exception:
            logger.warning("Screenshot upload failed", exc_info=True)
            return ""

    async def _ensure_screenshot_release(self) -> None:
        """Create the screenshots release if it doesn't exist."""
        try:
            await self._run_gh(
                "gh",
                "release",
                "view",
                self._SCREENSHOT_RELEASE_TAG,
                "--repo",
                self._repo,
            )
        except RuntimeError:
            # Release doesn't exist — create it
            await self._run_gh(
                "gh",
                "release",
                "create",
                self._SCREENSHOT_RELEASE_TAG,
                "--repo",
                self._repo,
                "--title",
                "Screenshot Assets",
                "--notes",
                "Auto-uploaded screenshots from bug reports",
                "--latest=false",
            )

    async def upload_screenshot_gist(self, png_base64: str) -> str:
        """Upload a base64-encoded PNG as a GitHub gist and return the raw URL.

        Returns an empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would upload screenshot gist")
            return ""

        # Strip optional data URI prefix
        if png_base64.startswith("data:"):
            _, _, png_base64 = png_base64.partition(",")

        try:
            png_bytes = base64.b64decode(png_base64, validate=True)
        except (ValueError, binascii.Error):
            logger.warning("Screenshot gist upload skipped: invalid base64 payload")
            return ""

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="hydraflow-screenshot-")
        try:
            try:
                f = os.fdopen(fd, "wb")
            except OSError:
                os.close(fd)
                raise
            with f:
                f.write(png_bytes)

            gist_args = [
                "gh",
                "gist",
                "create",
            ]
            if self._config.screenshot_gist_public:
                gist_args.append("--public")
            gist_args += ["--filename", "screenshot.png", tmp_path]

            output = await self._run_gh(*gist_args)
            return self._gist_raw_url(output, "screenshot.png")
        except Exception:
            logger.warning("Screenshot gist upload failed", exc_info=True)
            return ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _gist_raw_url(gist_output: str, filename: str) -> str:
        """Convert ``gh gist create`` output to a raw gist URL for *filename*."""
        gist_url = gist_output.strip()
        if "gist.github.com" not in gist_url:
            logger.warning("Unexpected gist create output: %s", gist_url[:200])
            return ""
        return (
            gist_url.replace("gist.github.com", "gist.githubusercontent.com")
            + f"/raw/{filename}"
        )
