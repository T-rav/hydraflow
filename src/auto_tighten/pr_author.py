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
        files = []
        for edit in ct.file_edits:
            p = Path(edit.path)
            p.write_text(edit.new_text)
            files.append(p)
        branch = f"auto-tighten/{ct.dedup_key.replace(':', '-')}"
        result = await self._opener(
            repo_root=self._root,
            branch=branch,
            files=files,
            pr_title=f"chore(auto-tighten): raise {ct.ratchet_id} floor to {ct.floor}",
            pr_body=f"Auto-tightening {ct.ratchet_id} to {ct.floor}. Evidence: {ct.evidence}.",
            base=self._base,
            auto_merge=True,
        )
        return getattr(result, "pr_url", None)
