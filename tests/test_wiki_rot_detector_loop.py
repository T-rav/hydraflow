"""Tests for WikiRotDetectorLoop (spec §4.9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])
    pr_manager.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = MagicMock()
    dedup.get.return_value = set()
    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = []
    return cfg, state, pr_manager, dedup, wiki_store


def _loop(env, *, enabled: bool = True) -> WikiRotDetectorLoop:
    cfg, state, pr, dedup, wiki_store = env
    return WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "wiki_rot_detector"
    assert loop._get_default_interval() == 604800


async def test_do_work_noop_when_no_repos(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
    assert stats["repos_scanned"] == 0
    _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_do_work_disabled_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    # The base class short-circuits ``run``, not ``_do_work``; we test the
    # explicit kill-switch guard at the top of ``_do_work``.
    stats = await loop._do_work()
    assert stats["status"] == "disabled"


async def test_do_work_autocloses_stale_escalation(tmp_path: Path, loop_env) -> None:
    """An escalation whose broken cite no longer exists at HEAD auto-closes
    after a complete scan (#9618 dead-letter class)."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)  # empty wiki — zero broken cites this tick
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 77,
                "title": "Wiki rot stuck: hydra/hydraflow cites missing "
                "src/gone.py:Sym",
                "body": "",
                "updated_at": "",
            }
        ]
    )
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    stats = await loop._do_work()

    pr.close_issue.assert_awaited_once_with(77)
    state.clear_wiki_rot_attempts.assert_called_with("hydra/hydraflow:src/gone.py:Sym")
    assert stats["autoclosed"] == 1


async def test_do_work_keeps_escalation_for_live_broken_cite(
    tmp_path: Path, loop_env
) -> None:
    """Escalations for cites still broken this tick must survive — including
    dedup-suppressed ones (already filed, still broken)."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text(
        "# Patterns\n\nThe guard lives in src/foo.py:bar - see ADR-0099.\n"
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]
    # Already filed + dedup'd on a prior tick — the filing path is skipped
    # but the cite is still broken, so the subject must count as active.
    dedup.get.return_value = {"wiki_rot_detector:hydra/hydraflow:src/foo.py:bar"}
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 78,
                "title": "Wiki rot stuck: hydra/hydraflow cites missing src/foo.py:bar",
                "body": "",
                "updated_at": "",
            }
        ]
    )
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    stats = await loop._do_work()

    pr.close_issue.assert_not_awaited()
    assert stats["autoclosed"] == 0


async def test_do_work_partial_scan_skips_autoclose(
    tmp_path: Path, loop_env, monkeypatch
) -> None:
    """A failed repo tick makes the detection set partial — auto-closing on
    it would kill real escalations for the failed repo's subjects."""
    cfg, state, pr, dedup, wiki_store = loop_env
    wiki_store.list_repos.return_value = ["hydra/hydraflow"]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)

    async def boom(slug: str, self_slug: str, budget: object) -> dict:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(loop, "_tick_repo", boom)

    stats = await loop._do_work()

    pr.list_issues_by_label.assert_not_awaited()
    pr.close_issue.assert_not_awaited()
    assert stats["autoclosed"] == 0


async def test_tick_repo_files_issue_on_broken_cite(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Seed a minimal wiki directory with one entry that cites a missing
    # symbol in a module that *does* exist.
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    entry = wiki_dir / "patterns.md"
    entry.write_text(
        "# Patterns\n\n## Entry A\n\n"
        "The guard lives in src/foo.py:bar - see ADR-0099.\n"
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    # Seed HydraFlow-self source so AST verification resolves to a real
    # module without the missing symbol.
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    pr.create_issue.assert_awaited_once()
    title, body, labels = pr.create_issue.await_args.args
    assert "Wiki rot" in title
    assert "src/foo.py:bar" in title
    assert "Did you mean: other" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_tick_repo_dedups_repeat_cite(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {f"wiki_rot_detector:{slug}:src/foo.py:bar"}
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_tick_repo_escalates_on_third_attempt(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Not already deduped — simulate "new" fire but 3rd attempt counter.
    dedup.get.return_value = set()
    state.get_wiki_rot_attempts.return_value = 2
    state.inc_wiki_rot_attempts.return_value = 3

    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["escalations"] == 1, stats
    assert stats["issues_filed"] == 1  # filed + escalated in same tick
    # Two create_issue calls: the find and the escalation.
    calls = pr.create_issue.await_args_list
    assert len(calls) == 2
    labels_escalate = calls[-1].args[2]
    assert set(labels_escalate) == {"hitl-escalation", "wiki-rot-stuck"}


# ---------------------------------------------------------------------------
# Structured WikiEntry consumption (issue #9936)
# ---------------------------------------------------------------------------
#
# Before #9936, ``_load_wiki_entries`` walked every ``.md`` file and treated
# the WHOLE FILE as one blob, titled under the file's ``# Heading``. Two
# regex-driven false positives fell out of that: (1) every broken cite in a
# multi-entry topic page was misattributed to the file heading instead of
# the entry that actually cited it, and (2) fenced-code "hints" from an
# unrelated entry sharing the file leaked into a finding that had nothing
# to do with them. Both are fixed by parsing the authoritative per-entry
# ``WikiEntry`` (``repo_wiki.parse_topic_page``) instead.


async def test_tick_repo_structured_entries_attribute_title_correctly(
    tmp_path: Path, loop_env
) -> None:
    """A broken cite in one entry of a multi-entry topic page must be filed
    under THAT entry's own title, not the topic file's ``# Heading``."""
    from repo_wiki import RepoWikiStore, WikiEntry

    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"

    real_store = RepoWikiStore(tmp_path / "real_wiki", self_slug=slug)
    real_store.ingest(
        slug,
        [
            WikiEntry(
                title="Alpha broken cite",
                content="See src/foo.py:missing_symbol for the guard.",
                source_type="manual",
                source_issue=101,
            ),
            WikiEntry(
                title="Beta unrelated hint",
                content=("```python\ndef totally_unrelated_hint():\n    pass\n```\n"),
                source_type="manual",
                source_issue=102,
            ),
        ],
    )
    wiki_dir = real_store._repo_dir(slug)
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    title, body, labels = pr.create_issue.await_args.args
    # Fixed: attributed to the originating entry, not the topic file's H1
    # ("Patterns" — the old regex-whole-file behavior would have used it
    # for every finding in the file, regardless of which entry cited it).
    assert "Alpha broken cite" in title
    assert "Patterns cites missing" not in title
    # Fixed: Beta's fenced-code hint must not leak into Alpha's finding —
    # under the old whole-file parse, extract_fenced_hints ran over BOTH
    # entries concatenated and would have surfaced this as "context".
    assert "totally_unrelated_hint" not in body
    # New: structured provenance is now available and surfaced.
    assert "#101 (manual)" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_shipped_claim_fires_via_structured_wiki_entry_fields(
    tmp_path: Path, loop_env
) -> None:
    """Structured entries carry ``fixed_in_pr``/``code_refs`` as authoritative
    ``WikiEntry`` fields (issue #9936 added them — previously silently
    dropped as unmodeled pydantic extras). The shipped-claim pass must read
    them directly rather than re-parsing the ``json:entry`` block
    RepoWikiStore already parsed once — this must work even though
    ``entry.content`` (the scanned ``body``) never contains that block."""
    from repo_wiki import RepoWikiStore, WikiEntry

    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"

    real_store = RepoWikiStore(tmp_path / "real_wiki", self_slug=slug)
    real_store.ingest(
        slug,
        [
            WikiEntry(
                title="Swap boundary",
                content="Prose about the swap boundary gotcha.",
                source_type="manual",
                source_issue=6295,
                fixed_in_pr="#8715",
                code_refs=("src/gone.py:vanished",),
            ),
        ],
    )
    wiki_dir = real_store._repo_dir(slug)
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    (tmp_path / "src").mkdir(exist_ok=True)  # module absent → code_ref dead
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    title, body, labels = pr.create_issue.await_args.args
    assert "#8715" in title
    assert "#8715" in body
    assert "#6295 (manual)" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_shipped_claim_clean_via_structured_fields_when_ref_resolves(
    tmp_path: Path, loop_env
) -> None:
    """A structured entry's ``fixed_in_pr`` claim with a live code_ref must
    not fire — mirrors the raw-fallback corroboration test but exercises
    the structured (``WikiEntry.fixed_in_pr``) path."""
    from repo_wiki import RepoWikiStore, WikiEntry

    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"

    real_store = RepoWikiStore(tmp_path / "real_wiki", self_slug=slug)
    real_store.ingest(
        slug,
        [
            WikiEntry(
                title="Half-state on skill failure",
                content="Prose about the guard.",
                source_type="manual",
                source_issue=6295,
                fixed_in_pr="#8713",
                code_refs=("src/live.py:present", "src/gone.py:vanished"),
            ),
        ],
    )
    wiki_dir = real_store._repo_dir(slug)
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "live.py").write_text("def present():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    await loop._do_work()

    assert not any("#8713" in c.args[0] for c in pr.create_issue.await_args_list), (
        pr.create_issue.await_args_list
    )


async def test_load_wiki_entries_falls_back_to_raw_for_non_topic_page_markdown(
    tmp_path: Path, loop_env
) -> None:
    """Markdown that isn't in the WikiEntry topic-page shape (no ``## ``
    sections, or none carrying a ``json:entry`` block) must still be
    scanned via the legacy whole-file path — preserving existing behavior
    for entries that still need it (glossary/feedback-style pages)."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "terms" / "actuator.md").parent.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "terms" / "actuator.md").write_text(
        "---\ncode_anchor: src/foo.py:bar\n---\n\n## Definition\n\nProse.\n"
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    title, body, labels = pr.create_issue.await_args.args
    assert "src/foo.py:bar" in title
    # No structured provenance for a raw-fallback row.
    assert "Entry source:" not in body


def _shipped_entry(pr_ref: str, code_refs: list[str]) -> str:
    """A wiki entry with a structured ``fixed_in_pr`` shipped claim."""
    import json

    block = json.dumps(
        {"id": "x", "rule": "r", "code_refs": code_refs, "fixed_in_pr": pr_ref}
    )
    return f"# Entry\n\nProse.\n\n```json:entry\n{block}\n```\n"


async def test_shipped_claim_fires_when_code_refs_all_dead(
    tmp_path: Path, loop_env
) -> None:
    """A ``fixed_in_pr`` claim whose code_refs no longer resolve is drift."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "gotchas.md").write_text(
        _shipped_entry("#8715", ["src/gone.py:vanished"])
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)  # module absent → code_ref dead
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    title, body, labels = pr.create_issue.await_args.args
    assert "#8715" in title
    assert "#8715" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_shipped_claim_clean_when_a_code_ref_resolves(
    tmp_path: Path, loop_env
) -> None:
    """At least one resolving code_ref corroborates the shipped claim."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "gotchas.md").write_text(
        _shipped_entry("#8713", ["src/live.py:present", "src/gone.py:vanished"])
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "live.py").write_text("def present():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    await loop._do_work()

    # The resolving code_ref corroborates the claim — but the dead second
    # code_ref still fires the ordinary per-cite pass. The shipped-claim
    # finding itself must NOT fire.
    assert not any("#8713" in c.args[0] for c in pr.create_issue.await_args_list), (
        pr.create_issue.await_args_list
    )


async def test_shipped_claim_dedups_repeat(tmp_path: Path, loop_env) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {f"wiki_rot_detector:{slug}:shipped #8715"}
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "gotchas.md").write_text(
        _shipped_entry("#8715", ["src/gone.py:vanished"])
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    await loop._do_work()

    assert not any("#8715" in c.args[0] for c in pr.create_issue.await_args_list)


async def test_shipped_claim_escalates_on_third_attempt(
    tmp_path: Path, loop_env
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = set()
    state.get_wiki_rot_attempts.return_value = 2
    state.inc_wiki_rot_attempts.return_value = 3
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "gotchas.md").write_text(
        _shipped_entry("#8715", ["src/gone.py:vanished"])
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["escalations"] == 1, stats
    escalation = pr.create_issue.await_args_list[-1]
    title, _body, labels = escalation.args
    assert set(labels) == {"hitl-escalation", "wiki-rot-stuck"}
    # Escalation title must parse back to the shipped subject via the
    # existing reconciler (``... cites missing shipped #8715``).
    assert "cites missing shipped #8715" in title


async def test_shipped_claim_escalation_subject_roundtrips(
    tmp_path: Path, loop_env
) -> None:
    """The shipped escalation title parses back to its dedup subject so the
    existing close-to-clear reconcile works unchanged."""
    from wiki_rot_detector_loop import _parse_escalation_subject

    slug = "hydra/hydraflow"
    title = f"Wiki rot stuck: {slug} cites missing shipped #8715"
    assert _parse_escalation_subject(title, "") == f"{slug}:shipped #8715"


async def test_shipped_claim_skipped_for_managed_repo(tmp_path: Path, loop_env) -> None:
    """Shipped-claim corroboration uses self-repo AST; managed repos (grep
    over wiki mirrors) are out of scope and must not fire it."""
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "other/managed"  # != cfg.repo (hydra/hydraflow)
    managed_dir = tmp_path / "wiki" / slug
    managed_dir.mkdir(parents=True)
    (managed_dir / "gotchas.md").write_text(
        _shipped_entry("#8715", ["src/gone.py:vanished"])
    )
    self_dir = tmp_path / "wiki" / "hydra" / "hydraflow"  # empty self wiki
    self_dir.mkdir(parents=True)

    def _repo_dir(s: str):
        return managed_dir if s == slug else self_dir

    wiki_store.repo_dir.side_effect = _repo_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    await loop._do_work()

    assert not any("#8715" in c.args[0] for c in pr.create_issue.await_args_list)


async def test_reconcile_clears_dedup_and_attempts(
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {
        f"wiki_rot_detector:{slug}:src/foo.py:bar",
        f"wiki_rot_detector:{slug}:src/foo.py:other",  # unrelated, stays
    }
    closed_payload = [
        {
            "number": 901,
            "title": f"Wiki rot stuck: {slug} cites missing src/foo.py:bar",
            "body": f"Repo: `{slug}`",
        },
    ]
    pr.list_closed_issues_by_label = AsyncMock(return_value=closed_payload)

    loop = _loop(loop_env)
    await loop._reconcile_closed_escalations()

    pr.list_closed_issues_by_label.assert_awaited_once_with("wiki-rot-stuck", limit=50)
    state.clear_wiki_rot_attempts.assert_any_call(f"{slug}:src/foo.py:bar")
    # set_all called with the surviving key.
    remaining_calls = [c.args[0] for c in dedup.set_all.call_args_list]
    assert remaining_calls, "dedup.set_all not invoked"
    assert f"wiki_rot_detector:{slug}:src/foo.py:bar" not in remaining_calls[-1]
    assert f"wiki_rot_detector:{slug}:src/foo.py:other" in remaining_calls[-1]


async def test_reconcile_noop_when_no_closed(loop_env) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])

    loop = _loop(loop_env)
    await loop._reconcile_closed_escalations()

    pr.list_closed_issues_by_label.assert_awaited_once_with("wiki-rot-stuck", limit=50)
    dedup.set_all.assert_not_called()
    state.clear_wiki_rot_attempts.assert_not_called()


async def test_reconcile_tolerates_port_failure(loop_env) -> None:
    """Port raises ⇒ reconcile returns without re-raising; no dedup mutation."""
    cfg, state, pr, dedup, wiki_store = loop_env
    pr.list_closed_issues_by_label = AsyncMock(side_effect=RuntimeError("gh down"))

    loop = _loop(loop_env)
    await loop._reconcile_closed_escalations()  # must not raise

    pr.list_closed_issues_by_label.assert_awaited_once()
    dedup.set_all.assert_not_called()
    state.clear_wiki_rot_attempts.assert_not_called()


async def test_reconcile_reraises_credit_exhausted(loop_env) -> None:
    """CreditExhaustedError from the port must propagate out of reconcile.

    reraise_on_credit_or_bug is a load-bearing call — billing signals must
    not be swallowed by the broad except block (wiki entry 0012 / CLAUDE.md).
    """
    from subprocess_util import CreditExhaustedError

    cfg, state, pr, dedup, wiki_store = loop_env
    pr.list_closed_issues_by_label = AsyncMock(
        side_effect=CreditExhaustedError("exhausted", resume_at=None)
    )

    loop = _loop(loop_env)
    with pytest.raises(CreditExhaustedError):
        await loop._reconcile_closed_escalations()

    dedup.set_all.assert_not_called()
    state.clear_wiki_rot_attempts.assert_not_called()


async def test_kill_switch_short_circuits_tick(loop_env) -> None:
    """Disabled kill-switch → no-op, no reconcile, no emission (spec §12.2)."""
    loop = _loop(loop_env, enabled=False)
    reconcile = AsyncMock(return_value=None)
    loop._reconcile_closed_escalations = reconcile
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    # Reconcile must not run when disabled.
    reconcile.assert_not_awaited()
    _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_trace_emission_lazy_import_tolerates_missing_module(
    loop_env,
    monkeypatch,
) -> None:
    """Importing ``trace_collector`` must not be required — the loop
    runs clean even when the module is absent (spec sibling lock).
    """
    import sys

    # Force ImportError on the emit path.
    monkeypatch.setitem(sys.modules, "trace_collector", None)
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"


async def test_trace_emission_invoked_on_tick_end(
    loop_env,
    monkeypatch,
) -> None:
    """When ``trace_collector`` is importable, ``emit_loop_subprocess_trace``
    is called at the end of ``_do_work`` with the real module signature
    ``(loop, command, exit_code, duration_ms, stderr_excerpt)``.
    """
    import sys
    import types

    fake = types.ModuleType("trace_collector")
    calls: list[dict] = []

    def _emit(
        loop: str,
        command: list,
        exit_code: int,
        duration_ms: int,
        stderr_excerpt: str | None = None,
    ) -> None:
        calls.append(
            {
                "loop": loop,
                "command": command,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stderr_excerpt": stderr_excerpt,
            }
        )

    fake.emit_loop_subprocess_trace = _emit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "trace_collector", fake)

    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
    assert len(calls) == 1, calls
    assert calls[0]["loop"] == "wiki_rot_detector"
    assert calls[0]["exit_code"] == 0
    assert calls[0]["command"] == [
        "PRPort.list_closed_issues_by_label",
        "wiki-rot-stuck",
        "limit=50",
    ]
    assert isinstance(calls[0]["duration_ms"], int)
