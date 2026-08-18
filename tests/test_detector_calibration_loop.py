"""DetectorCalibrationLoop — repeat-escalation churn miner (meta-observability).

The ADR-drift and fake-coverage FP campaigns each ran for weeks before a
human noticed the pattern: the same subject escalating repeatedly means the
DETECTOR is miscalibrated, not the code. This loop mines closed
``hitl-escalation`` issues, normalizes titles (``#N`` digit runs are entity
identity and stay verbatim; other bare digit runs like attempt counts and
elapsed times collapse to ``#`` — see #11405), and files one
``detector-calibration`` find issue per subject that escalated >= 2 times
inside the window.
Recursion stays bounded at one meta-layer (ADR-0045 §12.1): find issues
only, no escalation tier.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from detector_calibration_loop import DetectorCalibrationLoop, _normalize, template_key
from events import EventBus


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _closed(number: int, title: str, age_days: int = 1) -> dict:
    """Adapter-shaped closed-issue row: the churn window keys on
    ``closed_at`` (#9727); ``updated_at`` rides along for shape fidelity."""
    stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    return {
        "number": number,
        "title": title,
        "body": "",
        "updated_at": stamp,
        "closed_at": stamp,
    }


@pytest.fixture
def loop_env(tmp_path: Path):
    from github_cache_loop import GitHubDataCache

    # TTL 0 (#9814): every cached read refreshes through the pr mock so
    # per-test return_value mutations stay visible tick-to-tick.
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", github_cache_issue_list_ttl_s=0
    )
    state = MagicMock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    loop = DetectorCalibrationLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(asyncio.Event()),
        github_cache=GitHubDataCache(cfg, pr, MagicMock()),
    )
    return loop, pr


def test_normalize_collapses_volatile_numbers() -> None:
    a = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3"
    )
    b = _normalize(
        "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 7"
    )
    assert a == b
    c = _normalize("HITL: flaky test tests.a.test_x unresolved after 3 attempts")
    assert a != c


def test_normalize_keeps_hash_prefixed_numbers_as_identity() -> None:
    a = _normalize("Sampled re-audit disagreement: PR #10817 (gauntlet)")
    b = _normalize("Sampled re-audit disagreement: PR #11241 (gauntlet)")
    assert a != b


def test_template_key_rejects_no_entity_reference() -> None:
    assert (
        template_key(_normalize("HITL: flaky test unresolved after 3 attempts")) is None
    )


def test_template_key_rejects_degenerate_short_phrase() -> None:
    # Only one alphabetic token survives stripping "#N" — too generic to
    # be a meaningful template (#11427).
    assert template_key(_normalize("escalation #12345")) is None


def test_template_key_collapses_same_template_across_distinct_entities() -> None:
    a = template_key(_normalize("HITL: convergence oscillation detected for #9001"))
    b = template_key(_normalize("HITL: convergence oscillation detected for #9042"))
    assert a is not None
    assert a == b


def test_template_key_differs_across_distinct_templates() -> None:
    a = template_key(_normalize("HITL: convergence oscillation detected for #9001"))
    b = template_key(_normalize("HITL: fake coverage gap X unresolved for #9001"))
    assert a != b


async def test_repeat_churn_files_calibration_issue(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(
            102,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 6",
            age_days=10,
        ),
        _closed(103, "HITL: flaky test tests.a.test_x unresolved after 3 attempts"),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 1
    title, body, labels = pr.create_issue.await_args.args
    assert "Detector calibration" in title
    assert "#101" in body
    assert "#102" in body
    assert "hydraflow-find" in labels
    assert "detector-calibration" in labels


async def test_below_threshold_is_noop(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(103, "HITL: flaky test tests.a.test_x unresolved after 3 attempts"),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_window_excludes_old_closes(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            101,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
        ),
        _closed(
            102,
            "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 6",
            age_days=45,
        ),
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0


async def test_dedup_prevents_refiling(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    await loop._do_work()
    assert pr.create_issue.await_count == 1


async def test_recovery_autocloses_when_churn_stops(loop_env) -> None:
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    filed_body = pr.create_issue.await_args.args[1]
    # Churn stops: the window rolls past the pair. The rows STAY in the
    # scan (the 500-row closed scan is not date-filtered — only the in-loop
    # cutoff excludes them); an empty scan now means "gh degraded" and
    # skips auto-close entirely (#9814).
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3", age_days=45),
        _closed(102, "HITL: fake coverage gap X unresolved after 6", age_days=45),
    ]
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "whatever", "body": filed_body, "updated_at": ""}
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_awaited_once_with(77)
    assert stats["autoclosed"] == 1
    # Re-armed: the same churn recurring later files fresh.
    pr.list_issues_by_label.return_value = []
    pr.list_closed_issues_by_label.return_value = [
        _closed(201, "HITL: fake coverage gap X unresolved after 3"),
        _closed(202, "HITL: fake coverage gap X unresolved after 9"),
    ]
    await loop._do_work()
    assert pr.create_issue.await_count == 2


async def test_kill_switch_short_circuits(tmp_path: Path) -> None:
    from github_cache_loop import GitHubDataCache

    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", github_cache_issue_list_ttl_s=0
    )
    pr = AsyncMock()
    loop = DetectorCalibrationLoop(
        config=cfg,
        state=MagicMock(),
        pr_manager=pr,
        deps=_deps(asyncio.Event(), enabled=False),
        github_cache=GitHubDataCache(cfg, pr, MagicMock()),
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}


async def test_capped_scan_skips_autoclose(loop_env) -> None:
    """A truncated closed-issues scan can hide a still-churning subject —
    auto-closing on it would make the miner ITSELF churn (file → premature
    close → dedup re-arm → refile), the exact pathology it watches for."""
    from detector_calibration_loop import _SCAN_LIMIT

    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(101, "HITL: fake coverage gap X unresolved after 3"),
        _closed(102, "HITL: fake coverage gap X unresolved after 6"),
    ]
    await loop._do_work()
    filed_body = pr.create_issue.await_args.args[1]

    # Next tick: scan comes back AT the cap and the churning subject is
    # absent from it — indistinguishable from recovery. Must NOT close.
    capped = [
        _closed(1000 + i, f"HITL: trust-loop anomaly — w{i} kind{i}")
        for i in range(_SCAN_LIMIT)
    ]
    pr.list_closed_issues_by_label.return_value = capped
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "t", "body": filed_body, "updated_at": ""}
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_not_awaited()
    assert stats["autoclosed"] == 0


async def test_per_tick_cap_folds_overflow_into_one_summary(loop_env) -> None:
    """#10777: >cap churning subjects file `cap` issues + ONE summary, not N."""
    loop, pr = loop_env
    cap = loop._config.detector_calibration_max_issues_per_tick
    n_subjects = cap + 3
    closed = []
    num = 500
    for i in range(n_subjects):
        # Distinct non-numeric subject slugs → distinct normalized subjects;
        # two closes each puts every subject over the churn threshold.
        subj = (
            f"HITL: fake coverage gap FakeGitHub:surface-{chr(97 + i)} unresolved after"
        )
        closed.append(_closed(num, f"{subj} 3"))
        closed.append(_closed(num + 1, f"{subj} 6", age_days=2))
        num += 2
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()

    # cap individual issues + exactly one summary issue.
    assert pr.create_issue.await_count == cap + 1
    assert stats["filed"] == cap + 1
    summaries = [
        c.args[0]
        for c in pr.create_issue.await_args_list
        if "over per-tick filing cap" in c.args[0]
    ]
    assert len(summaries) == 1


async def test_at_cap_files_no_summary(loop_env) -> None:
    """Exactly `cap` churning subjects → all filed individually, no summary."""
    loop, pr = loop_env
    cap = loop._config.detector_calibration_max_issues_per_tick
    closed = []
    num = 700
    for i in range(cap):
        subj = (
            f"HITL: fake coverage gap FakeGitHub:region-{chr(97 + i)} unresolved after"
        )
        closed.append(_closed(num, f"{subj} 3"))
        closed.append(_closed(num + 1, f"{subj} 6", age_days=2))
        num += 2
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()

    assert pr.create_issue.await_count == cap
    assert stats["filed"] == cap
    assert not any(
        "over per-tick filing cap" in c.args[0] for c in pr.create_issue.await_args_list
    )


async def test_spray_fires_for_many_distinct_entities_under_one_template(
    loop_env,
) -> None:
    """#11427 — one template hitting >= spray_min_entities distinct #N
    entities files a spray finding even though no single entity repeats."""
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(900 + i, f"HITL: convergence oscillation detected for #{9001 + i}")
        for i in range(5)
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert stats["spraying_templates"] == 1
    assert stats["churning_subjects"] == 0
    title, body, labels = pr.create_issue.await_args.args
    assert "escalation spray" in title
    assert "5 entities" in title
    assert "Template-Key:" in body
    assert "detector-calibration" in labels


async def test_single_entity_repeated_stays_subject_class_never_spray(
    loop_env,
) -> None:
    """One entity re-firing 20x must classify as churn, never spray (#11427)."""
    loop, pr = loop_env
    pr.list_closed_issues_by_label.return_value = [
        _closed(
            910 + i,
            f"HITL: convergence oscillation detected for #9100 (attempt {i})",
        )
        for i in range(20)
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 1
    assert stats["churning_subjects"] == 1
    assert stats["spraying_templates"] == 0
    title, body, _ = pr.create_issue.await_args.args
    assert "escalation churn" in title
    assert "Norm-Key:" in body


async def test_spray_below_threshold_is_noop(loop_env) -> None:
    """Fewer than spray_min_entities distinct entities is not spray."""
    loop, pr = loop_env
    cfg_threshold = loop._config.detector_calibration_spray_min_entities
    pr.list_closed_issues_by_label.return_value = [
        _closed(920 + i, f"HITL: convergence oscillation detected for #{9200 + i}")
        for i in range(cfg_threshold - 1)
    ]
    stats = await loop._do_work()
    assert stats["filed"] == 0
    assert stats["spraying_templates"] == 0
    pr.create_issue.assert_not_awaited()


async def test_subject_folds_into_spraying_template_dedup_untouched(
    loop_env,
) -> None:
    """#11427 — a churning subject whose template is spraying this tick
    folds into the spray finding without filing or recording its own
    dedup key, so it re-files on its own once the spray clears."""
    loop, pr = loop_env
    closed = [
        _closed(950, "HITL: convergence oscillation detected for #9500"),
        _closed(951, "HITL: convergence oscillation detected for #9500"),
    ]
    for i in range(4):
        closed.append(
            _closed(960 + i, f"HITL: convergence oscillation detected for #{9600 + i}")
        )
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()
    # Only the spray finding files; #9500's subject finding is folded in.
    assert stats["filed"] == 1
    assert pr.create_issue.await_count == 1
    title, spray_body, _ = pr.create_issue.await_args.args
    assert "escalation spray" in title

    # Spray clears: the other 4 entities age out of the window, leaving
    # only #9500's two closes — churning persists, spraying does not.
    aged = [
        _closed(950, "HITL: convergence oscillation detected for #9500"),
        _closed(951, "HITL: convergence oscillation detected for #9500"),
    ]
    for i in range(4):
        aged.append(
            _closed(
                960 + i,
                f"HITL: convergence oscillation detected for #{9600 + i}",
                age_days=45,
            )
        )
    pr.list_closed_issues_by_label.return_value = aged
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "spray", "body": spray_body, "updated_at": ""}
    ]

    stats2 = await loop._do_work()
    # The fold never wrote #9500's dedup key, so the subject is free to
    # file now that the spray that folded it has cleared.
    assert stats2["filed"] == 1
    assert pr.create_issue.await_count == 2
    title2, body2, _ = pr.create_issue.await_args_list[1].args
    assert "escalation churn" in title2
    assert "#950" in body2
    # The spray finding itself auto-closes: its template stopped spraying.
    assert stats2["autoclosed"] == 1
    pr.close_issue.assert_awaited_once_with(77)


async def test_autoclose_skips_still_active_findings_for_both_classes(
    loop_env,
) -> None:
    """A still-spraying template and a still-churning subject open at the
    same time must both stay open — neither class's autoclose misfires
    on the other's still-active finding (#11427)."""
    loop, pr = loop_env
    closed = [
        _closed(970 + i, f"HITL: convergence oscillation detected for #{9700 + i}")
        for i in range(5)
    ]
    closed.append(_closed(980, "HITL: fake coverage gap X unresolved after 3"))
    closed.append(_closed(981, "HITL: fake coverage gap X unresolved after 6"))
    pr.list_closed_issues_by_label.return_value = closed

    await loop._do_work()
    assert pr.create_issue.await_count == 2
    spray_body = pr.create_issue.await_args_list[0].args[1]
    subject_body = pr.create_issue.await_args_list[1].args[1]

    # Next tick: identical closed rows, still within the window — both
    # classes remain active.
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "spray", "body": spray_body, "updated_at": ""},
        {"number": 78, "title": "subject", "body": subject_body, "updated_at": ""},
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_not_awaited()
    assert stats["autoclosed"] == 0
    assert stats["filed"] == 0  # dedup already holds both keys


async def test_autoclose_closes_cleared_spray_but_keeps_active_churn_open(
    loop_env,
) -> None:
    """Autoclose discriminates per-finding: a cleared spray closes while an
    unrelated, still-active churn finding stays open (#11427)."""
    loop, pr = loop_env
    closed = [
        _closed(1000 + i, f"HITL: convergence oscillation detected for #{9800 + i}")
        for i in range(5)
    ]
    closed.append(_closed(1010, "HITL: fake coverage gap Y unresolved after 3"))
    closed.append(_closed(1011, "HITL: fake coverage gap Y unresolved after 6"))
    pr.list_closed_issues_by_label.return_value = closed
    await loop._do_work()
    spray_body = pr.create_issue.await_args_list[0].args[1]
    subject_body = pr.create_issue.await_args_list[1].args[1]

    # The spray's 5 entities age out of the window; the churn subject's
    # two closes stay within it.
    aged = [
        _closed(
            1000 + i,
            f"HITL: convergence oscillation detected for #{9800 + i}",
            age_days=45,
        )
        for i in range(5)
    ]
    aged.append(_closed(1010, "HITL: fake coverage gap Y unresolved after 3"))
    aged.append(_closed(1011, "HITL: fake coverage gap Y unresolved after 6"))
    pr.list_closed_issues_by_label.return_value = aged
    pr.list_issues_by_label.return_value = [
        {"number": 77, "title": "spray", "body": spray_body, "updated_at": ""},
        {"number": 78, "title": "subject", "body": subject_body, "updated_at": ""},
    ]
    stats = await loop._do_work()
    pr.close_issue.assert_awaited_once_with(77)
    assert stats["autoclosed"] == 1


async def test_spray_per_tick_cap_folds_overflow_into_shared_summary(
    loop_env,
) -> None:
    """#11427/#10777 — spray findings share the subject class's per-tick
    filing cap; over-cap templates fold into ONE summary and record their
    dedup key so they are not individually re-filed next tick."""
    loop, pr = loop_env
    cap = loop._config.detector_calibration_max_issues_per_tick
    n_templates = cap + 2
    closed = []
    num = 2000
    for t in range(n_templates):
        letter = chr(97 + t)
        for e in range(5):
            closed.append(
                _closed(
                    num, f"HITL: trust-loop anomaly {letter} for #{3000 + t * 10 + e}"
                )
            )
            num += 1
    pr.list_closed_issues_by_label.return_value = closed

    stats = await loop._do_work()

    assert pr.create_issue.await_count == cap + 1
    assert stats["filed"] == cap + 1
    spray_titles = [
        c.args[0]
        for c in pr.create_issue.await_args_list
        if "escalation spray" in c.args[0]
    ]
    assert len(spray_titles) == cap
    summaries = [
        c.args[0]
        for c in pr.create_issue.await_args_list
        if "over per-tick filing cap" in c.args[0]
    ]
    assert len(summaries) == 1

    # Overflowed templates recorded their dedup key — re-running the same
    # tick must not re-file them individually.
    await loop._do_work()
    assert pr.create_issue.await_count == cap + 1
