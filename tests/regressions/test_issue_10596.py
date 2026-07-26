"""Regression for issue #10596.

``WikiRotDetectorLoop._shipped_claim_corroborated`` partitions each
``code_refs`` entry on ``:`` and, when AST verification of the symbol half
fails, falls back to ``verify_cite_grep(repo_root, module_path, symbol)``.

When a ``json:entry`` records a code ref as a *line reference*
(``foo.py:412``) rather than a ``path.py:Symbol`` cite, the symbol half is
the pure-numeric string ``"412"``. AST verification never resolves it, but
the grep fallback searches for the substring ``"412"`` in ``foo.py`` and
frequently matches incidental text (a line number, a literal, a hash), so
the ``fixed_in_pr`` claim is spuriously corroborated even though no live
symbol backs it. This is the inverse of the #10591 line-reference false
positive — a false *negative* for rot.

The fix mirrors the digit-guard added by #10591 (``extract_cites``) and the
constant-resolution of #10594 (``verify_cite_ast``): a purely-numeric symbol
half is a line reference, not a symbol, and must be skipped before the grep
fallback. Python identifiers never start with a digit, so a pure-numeric
tail is unambiguously a line reference. A genuine ``path.py:Symbol`` ref and
a bare-file ref must still corroborate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_citations import ShippedClaim
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _loop(tmp_path: Path) -> WikiRotDetectorLoop:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    return WikiRotDetectorLoop(
        config=cfg,
        state=MagicMock(),
        pr_manager=AsyncMock(),
        dedup=MagicMock(),
        wiki_store=MagicMock(),
        deps=deps,
    )


def _write_module(repo_root: Path, rel: str, body: str) -> None:
    target = repo_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_line_reference_code_ref_does_not_corroborate(tmp_path: Path) -> None:
    # A repo file whose text *incidentally* contains the digit string of a
    # line reference: the grep fallback would otherwise match "412" here.
    repo_root = tmp_path / "repo"
    _write_module(
        repo_root,
        "src/foo.py",
        "# arbitrary module\nMAX_RETRIES = 412  # incidental match\n",
    )
    loop = _loop(tmp_path)

    claim = ShippedClaim(
        pr_ref="#9999",
        code_refs=("src/foo.py:412",),
        raw="{}",
    )
    # A code_ref whose only symbol half is a line number must NOT count as a
    # live-symbol corroboration.
    assert loop._shipped_claim_corroborated(claim, repo_root) is False


def test_real_symbol_code_ref_still_corroborates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_module(
        repo_root,
        "src/foo.py",
        "def guard_symbol():\n    return 1\n",
    )
    loop = _loop(tmp_path)

    claim = ShippedClaim(
        pr_ref="#9999",
        code_refs=("src/foo.py:guard_symbol",),
        raw="{}",
    )
    assert loop._shipped_claim_corroborated(claim, repo_root) is True


def test_bare_file_code_ref_still_corroborates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _write_module(repo_root, "src/foo.py", "PLACEHOLDER = 1\n")
    loop = _loop(tmp_path)

    claim = ShippedClaim(
        pr_ref="#9999",
        code_refs=("src/foo.py",),
        raw="{}",
    )
    assert loop._shipped_claim_corroborated(claim, repo_root) is True


def test_line_ref_alongside_real_symbol_corroborates_via_symbol(
    tmp_path: Path,
) -> None:
    # When both a bogus line ref and a genuine symbol ref are present, the
    # claim is still corroborated — by the real symbol, never the line ref.
    repo_root = tmp_path / "repo"
    _write_module(
        repo_root,
        "src/foo.py",
        "def real_symbol():\n    return 141\n",
    )
    loop = _loop(tmp_path)

    claim = ShippedClaim(
        pr_ref="#9999",
        code_refs=("src/foo.py:141", "src/foo.py:real_symbol"),
        raw="{}",
    )
    assert loop._shipped_claim_corroborated(claim, repo_root) is True
