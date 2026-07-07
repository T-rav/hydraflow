from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from auto_tighten.models import ConfirmedTightening


class TighteningPrAuthor:
    def __init__(
        self,
        *,
        repo_root: Path,
        base: str,
        opener=None,
        open_pr_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self._root = repo_root
        self._base = base
        if opener is None:
            from auto_pr import open_automated_pr_async  # noqa: PLC0415

            opener = open_automated_pr_async
        self._opener = opener
        # Cross-tick dedup: skip opening when a tightening PR for this exact
        # floor is already open. Defaults to "no dedup" so unit tests that do
        # not wire it behave unchanged; production wires a gh probe.
        self._open_pr_exists = open_pr_exists or (lambda _branch: False)

    async def open(self, ct: ConfirmedTightening) -> str | None:
        """Open the tightening PR, returning its URL or ``None`` on skip/failure.

        Cross-tick dedup: if a tightening PR for this exact floor is already
        open (same branch head), skip before touching the working tree, so a
        stuck or slow-to-merge PR does not redo worktree and push work every
        tick. Also passes ``raise_on_failure=False`` to the opener so any
        residual failure (a race, a no-diff) resolves to a benign hold, not an
        exception. The caller (``AutoTightenLoop._do_work``) treats a falsy
        return as "no tightening this tick."
        """
        from auto_pr import _sanitize_branch_for_path  # noqa: PLC0415

        branch = f"auto-tighten/{_sanitize_branch_for_path(ct.dedup_key)}"
        if self._open_pr_exists(branch):
            return None

        files = []
        for edit in ct.file_edits:
            p = Path(edit.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(edit.new_text)
            files.append(p)
        result = await self._opener(
            repo_root=self._root,
            branch=branch,
            files=files,
            pr_title=f"chore(auto-tighten): raise {ct.ratchet_id} floor to {ct.floor}",
            pr_body=f"Auto-tightening {ct.ratchet_id} to {ct.floor}. Evidence: {ct.evidence}.",
            base=self._base,
            auto_merge=True,
            raise_on_failure=False,
        )
        return getattr(result, "pr_url", None)
