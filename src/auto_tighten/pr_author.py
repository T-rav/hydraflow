from __future__ import annotations

from pathlib import Path

from auto_tighten.models import ConfirmedTightening


class TighteningPrAuthor:
    def __init__(self, *, repo_root: Path, base: str, opener=None) -> None:
        self._root = repo_root
        self._base = base
        if opener is None:
            from auto_pr import open_automated_pr_async  # noqa: PLC0415

            opener = open_automated_pr_async
        self._opener = opener

    async def open(self, ct: ConfirmedTightening) -> str | None:
        """Open the tightening PR, returning its URL or ``None`` on failure.

        Passes ``raise_on_failure=False`` to the opener: a failed open (e.g.
        a duplicate branch head because the prior tick's PR is still open,
        or a no-diff) must resolve to a benign hold, not an exception. Cross-
        tick dedup on "PR already open" isn't wired yet (needs real ``gh``
        wiring) — until then, this is what keeps a stuck PR from spamming an
        error event every tick. The caller (``AutoTightenLoop._do_work``)
        already treats a falsy return as "no tightening this tick."
        """
        from auto_pr import _sanitize_branch_for_path  # noqa: PLC0415

        files = []
        for edit in ct.file_edits:
            p = Path(edit.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(edit.new_text)
            files.append(p)
        branch = f"auto-tighten/{_sanitize_branch_for_path(ct.dedup_key)}"
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
