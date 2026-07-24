"""Unit tests for `src/adr_drift.py` (ADR-0056 helper)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import (
    AdrRollupEntry,
    DriftFinding,
    FleetDriftBatch,
    _adr_file_in_diff,
    compute_drift,
    compute_drift_by_adr,
    partition_fleet_drift,
)
from adr_index import ADR, ADRIndex


def _write_adr(
    adr_dir: Path,
    *,
    number: int,
    title: str,
    status: str,
    related_files: list[str],
) -> Path:
    """Drop a minimal ADR file with a `Related:` line citing the given files."""
    related = ", ".join(f"`{f}`" for f in related_files)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** {status}\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    path = adr_dir / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    path.write_text(body)
    return path


@pytest.fixture
def adr_index(tmp_path: Path) -> ADRIndex:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=1,
        title="alpha",
        status="Accepted",
        related_files=["src/alpha.py"],
    )
    _write_adr(
        adr_dir,
        number=2,
        title="beta",
        status="Accepted",
        related_files=["src/beta.py", "src/shared.py"],
    )
    _write_adr(
        adr_dir,
        number=3,
        title="gamma",
        status="Superseded",
        related_files=["src/gamma.py"],
    )
    return ADRIndex(adr_dir)


def test_no_drift_when_only_non_src_files_changed(adr_index: ADRIndex) -> None:
    findings = compute_drift(adr_index, pr_number=10, changed_files=["docs/x.md"])
    assert findings == []


def test_drift_when_cited_src_changed_without_adr_in_diff(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "tests/test_alpha.py"],
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.adr.number == 1
    assert f.pr_number == 42
    assert f.changed_cited_files == ("src/alpha.py",)


def test_no_drift_when_adr_file_in_diff(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "docs/adr/0001-alpha.md"],
    )
    assert findings == []


def test_no_drift_when_adr_renamed_but_number_matches(adr_index: ADRIndex) -> None:
    """ADR-NNNN-* prefix match tolerates slug renames in the same diff."""
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "docs/adr/0001-alpha-renamed-slug.md"],
    )
    assert findings == []


def test_one_finding_per_drifted_adr_with_multiple_files(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/beta.py", "src/shared.py"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 2
    assert findings[0].changed_cited_files == ("src/beta.py", "src/shared.py")


def test_findings_sorted_by_adr_number(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/beta.py", "src/alpha.py"],
    )
    assert [f.adr.number for f in findings] == [1, 2]


def test_superseded_adr_does_not_drift(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/gamma.py"],
    )
    assert findings == []


def test_bare_citation_of_shared_infra_module_does_not_drift(tmp_path: Path) -> None:
    # Cross-cutting infrastructure modules (config dataclass, shared models,
    # Port protocols, post-merge handler) are bare-cited by many ADRs as a
    # dependency. A file-level touch is implementation churn, not a semantic
    # change to any one ADR's decision — it must NOT drift (the dominant
    # ADR-drift false-positive source). Require a :Symbol citation to drift.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=50,
        title="depends on config",
        status="Accepted",
        related_files=["src/config.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/config.py"]
    )
    assert findings == []


def test_bare_citation_of_pr_manager_does_not_drift(tmp_path: Path) -> None:
    # src/pr_manager.py is the GitHub PR/issue port wrapper — bare-cited as a
    # dependency by ADR-0005/0018/0045/0056 and touched by nearly every PR that
    # files an issue or PR. It is shared-infra: a file-level touch must NOT drift
    # (the residual false-positive source after #9397; resolves the stuck
    # ADR-0005/0018/0056 drift escalations). Owning a pr_manager symbol still
    # requires a :Symbol citation to drift (see test below).
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=53,
        title="depends on pr_manager",
        status="Accepted",
        related_files=["src/pr_manager.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/pr_manager.py"]
    )
    assert findings == []


def test_symbol_citation_of_pr_manager_still_drifts(tmp_path: Path) -> None:
    # An ADR that genuinely owns a pr_manager symbol (e.g. ADR-0018 cites
    # PRManager.upload_screenshot_gist) still drifts when that symbol changes.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=54,
        title="owns a pr_manager symbol",
        status="Accepted",
        related_files=["src/pr_manager.py:PRManager.upload_screenshot_gist"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/pr_manager.py:PRManager.upload_screenshot_gist"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 54


def test_symbol_citation_of_shared_infra_module_still_drifts(tmp_path: Path) -> None:
    # An ADR that genuinely owns a shared-infra symbol cites it at :Symbol
    # granularity and still drifts when that symbol changes.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=51,
        title="owns config schema",
        status="Accepted",
        related_files=["src/config.py:HydraFlowConfig"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/config.py:HydraFlowConfig"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 51


def test_bare_citation_of_non_infra_module_still_drifts(tmp_path: Path) -> None:
    # Regression guard: the shared-infra suppression must not change file-level
    # drift for ordinary (non-infra) cited modules.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=52,
        title="owns widget",
        status="Accepted",
        related_files=["src/widget.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/widget.py"]
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 52


@pytest.mark.parametrize(
    "module",
    [
        "src/dashboard.py",
        "src/server.py",
        "src/repo_runtime.py",
        "src/contract_recording.py",
        "src/contract_diff.py",
        "src/contract_refresh_loop.py",
        "src/review_advisor.py",
        "src/review_phase/_phase.py",
    ],
)
def test_recurring_fp_module_bare_citation_does_not_drift(
    tmp_path: Path, module: str
) -> None:
    # 2026-06-13: these high-churn modules are bare-cited as dependency pointers
    # by their pattern ADRs (dashboard/server/repo_runtime by the dashboard +
    # multi-repo ADRs; contract_* by ADR-0047/0052). A bare file-level touch is
    # implementation churn and must NOT drift — the recurring source of the
    # "ADR drift unresolved after 3" HITL escalations. An ADR that genuinely
    # owns a symbol in one of these still cites it at :Symbol granularity.
    # 2026-07-24 (#10411): review_advisor.py/review_phase/_phase.py joined —
    # the next-highest-churn review-path modules, bare-cited as dependency
    # pointers by ADR-0059/0094/0095/0102 and others; every review-path PR was
    # drifting a batch of those ADRs.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=60,
        title="depends on infra",
        status="Accepted",
        related_files=[module],
    )
    findings = compute_drift(ADRIndex(adr_dir), pr_number=1, changed_files=[module])
    assert findings == []


def test_real_adrs_do_not_drift_on_dependency_only_touches() -> None:
    # End-to-end regression for the recurring ADR-drift false positives that
    # filled the HITL queue (#9526/#9514/#9513/#9488 + the dashboard cluster
    # #9497/#9507/#9418/#9414). Touching these modules in the production case
    # (bare paths, no symbol evidence) must NOT drift the Accepted/Proposed ADRs
    # that merely cite them as dependencies. A new ADR that bare-cites one of
    # these (instead of a :Symbol) will trip this guard — by design.
    repo_root = Path(__file__).resolve().parents[1]
    idx = ADRIndex(repo_root / "docs" / "adr")
    touches = [
        "src/agent_cli.py",
        "src/dashboard.py",
        "src/server.py",
        "src/repo_runtime.py",
        "src/trust_fleet_sanity_loop.py",
        "src/contract_recording.py",
        "src/contract_diff.py",
        "src/contract_refresh_loop.py",
    ]
    findings = compute_drift(idx, pr_number=9999, changed_files=touches)
    drifted = sorted({f.adr.number for f in findings})
    assert drifted == [], (
        f"dependency-only touches drifted ADRs {drifted}; the cited module(s) "
        "must be shared-infra or symbol-qualified in the owning ADR"
    )


def test_adr_file_in_diff_helper(adr_index: ADRIndex) -> None:
    adr = next(a for a in adr_index.adrs() if a.number == 1)
    assert _adr_file_in_diff(adr, ["docs/adr/0001-alpha.md"])
    assert _adr_file_in_diff(adr, ["docs/adr/0001-renamed.md"])
    assert not _adr_file_in_diff(adr, ["docs/adr/0002-beta.md"])
    assert not _adr_file_in_diff(adr, ["src/alpha.py"])


def test_drift_finding_is_immutable() -> None:
    f = DriftFinding(
        adr=ADR(number=1, title="x", status="Accepted", summary=""),
        pr_number=1,
        changed_cited_files=("src/x.py",),
    )
    with pytest.raises(AttributeError):  # frozen dataclass
        f.pr_number = 2  # type: ignore[misc]


def test_compute_drift_by_adr_groups_multiple_prs(adr_index: ADRIndex) -> None:
    """#8987 — 3 PRs drifting the same ADR collapse into one rollup entry."""
    rollups = compute_drift_by_adr(
        adr_index,
        [
            (10, ["src/alpha.py"]),
            (11, ["src/alpha.py", "tests/x.py"]),
            (12, ["src/alpha.py"]),
        ],
    )
    assert len(rollups) == 1
    entry = rollups[0]
    assert entry.adr.number == 1
    assert entry.pr_numbers == (10, 11, 12)
    assert len(entry.contributors) == 3


def test_compute_drift_by_adr_one_pr_n_adrs(adr_index: ADRIndex) -> None:
    """#8987 — one PR drifting two ADRs yields two rollup entries."""
    rollups = compute_drift_by_adr(
        adr_index,
        [(99, ["src/alpha.py", "src/beta.py"])],
    )
    assert [e.adr.number for e in rollups] == [1, 2]
    for entry in rollups:
        assert entry.pr_numbers == (99,)


def test_compute_drift_by_adr_skips_prs_with_adr_in_diff(adr_index: ADRIndex) -> None:
    """A PR whose diff includes the ADR file is silently skipped for that ADR."""
    rollups = compute_drift_by_adr(
        adr_index,
        [
            (10, ["src/alpha.py"]),
            (11, ["src/alpha.py", "docs/adr/0001-alpha.md"]),
        ],
    )
    assert len(rollups) == 1
    assert rollups[0].pr_numbers == (10,)


def test_compute_drift_by_adr_empty_input(adr_index: ADRIndex) -> None:
    assert compute_drift_by_adr(adr_index, []) == []


def test_adr_rollup_entry_is_immutable(adr_index: ADRIndex) -> None:
    adr = next(a for a in adr_index.adrs() if a.number == 1)
    entry = AdrRollupEntry(
        adr=adr,
        contributors=(
            DriftFinding(adr=adr, pr_number=1, changed_cited_files=("src/alpha.py",)),
        ),
    )
    with pytest.raises(AttributeError):  # frozen dataclass
        entry.adr = adr  # type: ignore[misc]


# --- #9662: partition_fleet_drift / FleetDriftBatch ---


@pytest.fixture
def fleet_index(tmp_path: Path) -> ADRIndex:
    """Six single-module owned ADRs (numbers 101–106) + files they cite."""
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    for i in range(1, 7):
        _write_adr(
            adr_dir,
            number=100 + i,
            title=f"loop{i}",
            status="Accepted",
            related_files=[f"src/loop{i}.py"],
        )
    return ADRIndex(adr_dir)


def test_fleet_pr_batches_into_one_entry(fleet_index: ADRIndex) -> None:
    """One PR drifting 5 ADRs (>= threshold 4) → exactly one FleetDriftBatch;
    NONE of its findings appear in the per-ADR list (no double-filing)."""
    per_adr, batches = partition_fleet_drift(
        fleet_index,
        [(9592, [f"src/loop{i}.py" for i in range(1, 6)])],
        fleet_threshold=4,
    )
    assert per_adr == []
    assert len(batches) == 1
    batch = batches[0]
    assert batch.pr_number == 9592
    assert batch.adr_numbers == (101, 102, 103, 104, 105)
    for entry in batch.entries:
        assert entry.pr_numbers == (9592,)
        assert len(entry.contributors) == 1


def test_below_threshold_pr_stays_per_adr(fleet_index: ADRIndex) -> None:
    """A PR drifting 3 ADRs (< threshold 4) keeps the per-ADR shape."""
    per_adr, batches = partition_fleet_drift(
        fleet_index,
        [(100, ["src/loop1.py", "src/loop2.py", "src/loop3.py"])],
        fleet_threshold=4,
    )
    assert batches == []
    assert [e.adr.number for e in per_adr] == [101, 102, 103]


def test_partition_matches_compute_drift_by_adr_below_threshold(
    adr_index: ADRIndex,
) -> None:
    """Behavior-identity guard on the ``_aggregate_by_adr`` extraction:
    with no PR at threshold, the per-ADR list is exactly what
    ``compute_drift_by_adr`` produces (byte-for-byte)."""
    pr_diffs = [
        (10, ["src/alpha.py"]),
        (11, ["src/alpha.py", "src/beta.py", "tests/x.py"]),
        (12, ["src/alpha.py", "docs/adr/0001-alpha.md"]),
    ]
    per_adr, batches = partition_fleet_drift(adr_index, pr_diffs, fleet_threshold=4)
    assert batches == []
    assert per_adr == compute_drift_by_adr(adr_index, pr_diffs)


def test_mixed_fleet_and_normal_prs_partition_independently(
    fleet_index: ADRIndex,
) -> None:
    """A fleet PR and a normal PR drifting an overlapping ADR: the fleet PR's
    finding goes ONLY to the batch; the normal PR's finding for the same ADR
    stays per-ADR with only its own contributor."""
    per_adr, batches = partition_fleet_drift(
        fleet_index,
        [
            (200, [f"src/loop{i}.py" for i in range(1, 5)]),  # fleet: 4 ADRs
            (201, ["src/loop1.py"]),  # normal: 1 ADR, overlaps the fleet PR
        ],
        fleet_threshold=4,
    )
    assert len(batches) == 1
    assert batches[0].pr_number == 200
    assert batches[0].adr_numbers == (101, 102, 103, 104)
    assert [e.adr.number for e in per_adr] == [101]
    assert per_adr[0].pr_numbers == (201,)  # fleet PR 200 NOT double-filed


def test_adr_file_in_diff_does_not_count_toward_threshold(
    fleet_index: ADRIndex,
) -> None:
    """Self-coverage carries over: an ADR whose own file is in the PR's diff
    contributes no finding — dropping the PR below the fleet threshold."""
    per_adr, batches = partition_fleet_drift(
        fleet_index,
        [
            (
                300,
                [
                    "src/loop1.py",
                    "src/loop2.py",
                    "src/loop3.py",
                    "src/loop4.py",
                    "docs/adr/0104-loop4.md",  # ADR-0104 covered by its own file
                ],
            )
        ],
        fleet_threshold=4,
    )
    assert batches == []  # 3 findings < threshold 4
    assert [e.adr.number for e in per_adr] == [101, 102, 103]


def test_batches_sorted_by_pr_number(fleet_index: ADRIndex) -> None:
    fleet_files = [f"src/loop{i}.py" for i in range(1, 5)]
    _, batches = partition_fleet_drift(
        fleet_index,
        [(402, fleet_files), (401, fleet_files)],
        fleet_threshold=4,
    )
    assert [b.pr_number for b in batches] == [401, 402]


def test_partition_empty_input(fleet_index: ADRIndex) -> None:
    assert partition_fleet_drift(fleet_index, [], fleet_threshold=4) == ([], [])


def test_partition_rejects_threshold_below_two(fleet_index: ADRIndex) -> None:
    with pytest.raises(ValueError, match="fleet_threshold"):
        partition_fleet_drift(fleet_index, [], fleet_threshold=1)


def test_fleet_drift_batch_is_immutable(fleet_index: ADRIndex) -> None:
    _, batches = partition_fleet_drift(
        fleet_index,
        [(500, [f"src/loop{i}.py" for i in range(1, 5)])],
        fleet_threshold=4,
    )
    batch = batches[0]
    with pytest.raises(AttributeError):  # frozen dataclass
        batch.pr_number = 1  # type: ignore[misc]
    assert isinstance(batch, FleetDriftBatch)


# --- #10411: churn/fan-out-derived shared-infra auto-suppression ---
# The manual `_SHARED_INFRA_MODULES` allowlist grows one module at a time
# (whack-a-mole). A `src/` file bare-cited by >= `shared_infra_fanout_threshold`
# live (Accepted/Proposed) ADRs is automatically treated as shared infra —
# same suppression effect, derived from citation fan-out instead of a
# hand-maintained list. Threshold is opt-in (default `None` disables it) so
# every pre-existing test above keeps its exact prior behavior unchanged.


def _write_n_bare_citing_adrs(
    adr_dir: Path, *, start_number: int, count: int, path: str
) -> None:
    for i in range(count):
        _write_adr(
            adr_dir,
            number=start_number + i,
            title=f"fanout{i}",
            status="Accepted",
            related_files=[path],
        )


def test_fanout_below_threshold_still_drifts(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=200, count=3, path="src/widget.py")
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/widget.py"],
        shared_infra_fanout_threshold=4,
    )
    assert sorted(f.adr.number for f in findings) == [200, 201, 202]


def test_fanout_at_threshold_suppresses_all_contributors(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=210, count=4, path="src/widget.py")
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/widget.py"],
        shared_infra_fanout_threshold=4,
    )
    assert findings == []


def test_symbol_citation_unaffected_by_other_adrs_bare_fanout(tmp_path: Path) -> None:
    """A genuinely symbol-owning ADR still drifts even when 4 OTHER ADRs
    bare-cite the same file and push its fan-out to (and past) the
    threshold — those 4 are suppressed, the symbol-owning one is not."""
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=220, count=4, path="src/widget.py")
    _write_adr(
        adr_dir,
        number=230,
        title="owns a widget symbol",
        status="Accepted",
        related_files=["src/widget.py:Widget.render"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/widget.py:Widget.render"],
        shared_infra_fanout_threshold=4,
    )
    assert [f.adr.number for f in findings] == [230]


def test_shared_infra_allowlist_wins_regardless_of_threshold(tmp_path: Path) -> None:
    """The manual allowlist still suppresses even with a very high threshold
    (fan-out of 1 never reaches it) — the two suppression paths are OR'd."""
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=240,
        title="depends on config",
        status="Accepted",
        related_files=["src/config.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/config.py"],
        shared_infra_fanout_threshold=100,
    )
    assert findings == []


def test_fanout_threshold_defaults_to_disabled(tmp_path: Path) -> None:
    """Omitting the kwarg entirely preserves pre-#10411 behavior: no
    fan-out-derived suppression, however high the fan-out."""
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=250, count=10, path="src/widget.py")
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/widget.py"]
    )
    assert len(findings) == 10


def test_compute_drift_by_adr_threads_fanout_threshold(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=260, count=4, path="src/widget.py")
    rollups = compute_drift_by_adr(
        ADRIndex(adr_dir),
        [(1, ["src/widget.py"])],
        shared_infra_fanout_threshold=4,
    )
    assert rollups == []


def test_partition_fleet_drift_threads_fanout_threshold(tmp_path: Path) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_n_bare_citing_adrs(adr_dir, start_number=270, count=4, path="src/widget.py")
    per_adr, batches = partition_fleet_drift(
        ADRIndex(adr_dir),
        [(1, ["src/widget.py"])],
        fleet_threshold=4,
        shared_infra_fanout_threshold=4,
    )
    assert per_adr == []
    assert batches == []
