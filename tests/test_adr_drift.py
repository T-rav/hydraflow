"""Unit tests for `src/adr_drift.py` (ADR-0056 helper)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import (
    AdrRollupEntry,
    CitationNudge,
    DriftFinding,
    FleetDriftBatch,
    _adr_file_in_diff,
    _bare_citation_fanout,
    _citation_drifts,
    _is_shared_infra,
    bare_infra_citation_nudges,
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


# ---------------------------------------------------------------------------
# Churn-derived shared-infra suppression (#10456)
# ---------------------------------------------------------------------------


def _write_fanout_adrs(
    adr_dir: Path, *, count: int, module: str, bare: bool = True
) -> None:
    """Write *count* Accepted ADRs that each cite *module*.

    ``bare=True`` cites the file with no ``:Symbol`` tail (counts toward
    fan-out); ``bare=False`` cites ``{module}:Owner`` (symbol-qualified —
    must never be fan-out-suppressed).
    """
    cited = module if bare else f"{module}:Owner"
    for i in range(count):
        _write_adr(
            adr_dir,
            number=800 + i,
            title=f"cites hot {i}",
            status="Accepted",
            related_files=[cited],
        )


def test_bare_citation_fanout_counts_only_bare_citations(tmp_path: Path) -> None:
    # _bare_citation_fanout counts ADRs that cite the path bare (empty symbol
    # set); a :Symbol citation of the same file does not count.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=3, module="src/hot.py", bare=True)
    _write_adr(
        adr_dir,
        number=900,
        title="owns hot symbol",
        status="Accepted",
        related_files=["src/hot.py:Owner"],
    )
    idx = ADRIndex(adr_dir)
    adrs = idx.adrs_touching(["src/hot.py"])["src/hot.py"]
    assert _bare_citation_fanout("src/hot.py", adrs) == 3


def test_high_fanout_bare_citation_is_auto_suppressed(tmp_path: Path) -> None:
    # A src/ module bare-cited by >= threshold live ADRs is treated as shared
    # infra WITHOUT a manual `_SHARED_INFRA_MODULES` edit: no drift fires.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=4, module="src/hot.py", bare=True)
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/hot.py"],
        shared_infra_fanout_threshold=4,
    )
    assert findings == []


def test_below_threshold_bare_citation_still_drifts(tmp_path: Path) -> None:
    # Fan-out below the threshold must NOT suppress: genuine drift still fires.
    # Guards the off-by-one that would silently mask real single/low-fan-out
    # drift.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=3, module="src/hot.py", bare=True)
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/hot.py"],
        shared_infra_fanout_threshold=4,
    )
    assert sorted(f.adr.number for f in findings) == [800, 801, 802]


def test_no_threshold_preserves_prior_bare_citation_drift(tmp_path: Path) -> None:
    # Parity: with the default (threshold=None) a high-fan-out bare citation
    # drifts exactly as before — the derived suppression is opt-in.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=5, module="src/hot.py", bare=True)
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/hot.py"],
    )
    assert sorted(f.adr.number for f in findings) == [800, 801, 802, 803, 804]


def test_symbol_owner_still_drifts_regardless_of_fanout(tmp_path: Path) -> None:
    # A genuinely symbol-owning ADR still drifts on its symbol even when many
    # OTHER ADRs bare-cite the same high-fan-out file. Fan-out suppression is
    # only for bare citations.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=5, module="src/hot.py", bare=True)
    _write_adr(
        adr_dir,
        number=910,
        title="owns hot symbol",
        status="Accepted",
        related_files=["src/hot.py:Owner"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/hot.py:Owner"],
        shared_infra_fanout_threshold=4,
    )
    assert [f.adr.number for f in findings] == [910]


def test_allowlist_suppression_independent_of_fanout(tmp_path: Path) -> None:
    # The manual `_SHARED_INFRA_MODULES` path still suppresses even when the
    # derived fan-out path is disabled (threshold=None): the two are OR'd.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=920,
        title="depends on config",
        status="Accepted",
        related_files=["src/config.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/config.py"],
    )
    assert findings == []


def test_fanout_threshold_threads_through_partition_fleet_drift(
    tmp_path: Path,
) -> None:
    # The public fleet-partition entry point honours the derived suppression:
    # a high-fan-out bare-cited module produces no per-ADR rollups.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=4, module="src/hot.py", bare=True)
    rollups, batches = partition_fleet_drift(
        ADRIndex(adr_dir),
        [(1, ["src/hot.py"])],
        fleet_threshold=2,
        shared_infra_fanout_threshold=4,
    )
    assert rollups == []
    assert batches == []


def test_fanout_threshold_threads_through_compute_drift_by_adr(
    tmp_path: Path,
) -> None:
    # The rollup/reconcile entry point honours the derived suppression too, so
    # a rollup that recomputes empty under fan-out suppression can auto-close.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_fanout_adrs(adr_dir, count=4, module="src/hot.py", bare=True)
    rollups = compute_drift_by_adr(
        ADRIndex(adr_dir),
        [(1, ["src/hot.py"])],
        shared_infra_fanout_threshold=4,
    )
    assert rollups == []


def _adr_with_symbols(
    number: int,
    source_symbols: dict[str, frozenset[str]],
    *,
    status: str = "Accepted",
) -> ADR:
    """Build a minimal ADR carrying only the citation data the nudge reads."""
    return ADR(
        number=number,
        title=f"adr-{number}",
        status=status,
        summary="",
        source_files=frozenset(source_symbols),
        source_symbols=source_symbols,
    )


def test_bare_shared_infra_citation_yields_one_nudge() -> None:
    # #10458 — an ADR bare-citing a known shared-infra module gets nudged to
    # re-cite at :Symbol granularity.
    adr = _adr_with_symbols(500, {"src/config.py": frozenset()})
    nudges = bare_infra_citation_nudges([adr])
    assert nudges == [
        CitationNudge(
            adr_number=500,
            path="src/config.py",
            suggestion="src/config.py:<Symbol>",
        )
    ]


def test_symbol_qualified_shared_infra_citation_yields_no_nudge() -> None:
    # The ADR already cites at :Symbol granularity, so it already drifts
    # correctly — nothing to nudge.
    adr = _adr_with_symbols(501, {"src/config.py": frozenset({"HydraFlowConfig"})})
    assert bare_infra_citation_nudges([adr]) == []


def test_bare_non_shared_infra_citation_yields_no_nudge() -> None:
    # A bare citation to an ordinary src/ module still drifts on any touch, so
    # there is nothing to nudge (no suppression to compensate for).
    adr = _adr_with_symbols(502, {"src/some_feature.py": frozenset()})
    assert bare_infra_citation_nudges([adr]) == []


def test_non_src_bare_citation_yields_no_nudge() -> None:
    # The shared-infra rule is scoped to src/ modules; a docs/ citation is out
    # of scope even if bare.
    adr = _adr_with_symbols(503, {"docs/whatever.md": frozenset()})
    assert bare_infra_citation_nudges([adr]) == []


@pytest.mark.parametrize("status", ["Superseded", "Deprecated", "Unknown"])
def test_non_live_adr_bare_citation_yields_no_nudge(status: str) -> None:
    # #10565 -- drift-suppression (ADRIndex.adrs_touching) never touches a
    # non-live ADR in the first place, so there is nothing for the nudge to
    # "exactly mirror" for one. A Superseded/Deprecated/Unknown ADR that
    # bare-cites a shared-infra module must not be nudged.
    adr = _adr_with_symbols(504, {"src/config.py": frozenset()}, status=status)
    assert bare_infra_citation_nudges([adr]) == []


def test_fanout_excludes_non_live_adrs_from_count() -> None:
    # #10565 -- the fan-out that feeds the nudge's shared-infra derivation must
    # count only live bare-citers, matching compute_drift's adrs_touching
    # scope. 3 live + 1 non-live bare citer of the same module must NOT cross
    # a threshold of 4 (the non-live citer doesn't count).
    adrs = [_adr_with_symbols(n, {"src/hot.py": frozenset()}) for n in range(600, 603)]
    adrs.append(
        _adr_with_symbols(603, {"src/hot.py": frozenset()}, status="Superseded")
    )
    assert bare_infra_citation_nudges(adrs, shared_infra_fanout_threshold=4) == []


def test_high_fanout_bare_citation_is_nudged_when_threshold_given() -> None:
    # #10456 forward-compat: a churn-derived shared-infra module (>= threshold
    # live bare citations) is nudged too, on top of the manual allowlist.
    adrs = [_adr_with_symbols(n, {"src/hot.py": frozenset()}) for n in range(600, 604)]
    nudged_paths = {
        (n.adr_number, n.path)
        for n in bare_infra_citation_nudges(adrs, shared_infra_fanout_threshold=4)
    }
    assert nudged_paths == {(n, "src/hot.py") for n in range(600, 604)}
    # Default (threshold=None) uses the manual allowlist only — src/hot.py is
    # not on it, so no nudge.
    assert bare_infra_citation_nudges(adrs) == []


def test_nudges_sorted_by_adr_number_then_path() -> None:
    adrs = [
        _adr_with_symbols(
            700, {"src/pr_manager.py": frozenset(), "src/config.py": frozenset()}
        ),
        _adr_with_symbols(699, {"src/models.py": frozenset()}),
    ]
    result = [(n.adr_number, n.path) for n in bare_infra_citation_nudges(adrs)]
    assert result == [
        (699, "src/models.py"),
        (700, "src/config.py"),
        (700, "src/pr_manager.py"),
    ]


def test_empty_input_yields_empty_nudge_list() -> None:
    assert bare_infra_citation_nudges([]) == []


def test_nudges_couple_exactly_to_shared_infra_suppression() -> None:
    # Single-source-of-truth invariant (#10458): the nudge fires on exactly the
    # bare (ADR, path) pairs `_citation_drifts` suppresses as shared infra.
    # Both route through `_is_shared_infra`, so they can never diverge — this
    # pins that coupling across allowlist AND fan-out branches.
    threshold = 4
    adrs = [
        # allowlist bare -> suppressed -> nudged
        _adr_with_symbols(800, {"src/config.py": frozenset()}),
        # ordinary bare, low fan-out -> drifts -> not nudged
        _adr_with_symbols(801, {"src/lonely.py": frozenset()}),
        # symbol-qualified allowlist -> drifts on its symbol -> not nudged
        _adr_with_symbols(802, {"src/config.py": frozenset({"HydraFlowConfig"})}),
    ]
    # Push src/hot.py over the fan-out threshold with 4 bare citers.
    adrs += [_adr_with_symbols(n, {"src/hot.py": frozenset()}) for n in range(810, 814)]
    # #10565: non-live ADRs mixed in — drift-suppression (ADRIndex.adrs_touching)
    # never sees these, so they must never be nudged and must never contribute
    # to any other ADR's fan-out either. This is the exact blind spot that let
    # the bug ship green: every fixture ADR used to hardcode status="Accepted".
    adrs.append(
        _adr_with_symbols(820, {"src/config.py": frozenset()}, status="Superseded")
    )
    adrs.append(
        _adr_with_symbols(821, {"src/hot.py": frozenset()}, status="Deprecated")
    )

    nudged_pairs = {
        (n.adr_number, n.path)
        for n in bare_infra_citation_nudges(
            adrs, shared_infra_fanout_threshold=threshold
        )
    }
    assert 820 not in {number for number, _ in nudged_pairs}
    assert 821 not in {number for number, _ in nudged_pairs}

    live_adrs = [a for a in adrs if a.is_live]
    expected_suppressed: set[tuple[int, str]] = set()
    for adr in live_adrs:
        for path, cited in adr.source_symbols.items():
            if cited or not path.startswith("src/"):
                continue  # only bare src/ citations are eligible for suppression
            fanout = _bare_citation_fanout(path, live_adrs)
            drifts = _citation_drifts(
                adr,
                path,
                frozenset(),
                fanout=fanout,
                fanout_threshold=threshold,
            )
            if not drifts:  # suppressed as shared infra
                expected_suppressed.add((adr.number, path))

    assert nudged_pairs == expected_suppressed
    # Sanity: the invariant is non-trivial — it actually caught some pairs.
    assert expected_suppressed


def test_is_shared_infra_allowlist_and_fanout_branches() -> None:
    # Allowlist membership alone suppresses, regardless of fan-out.
    assert _is_shared_infra("src/config.py")
    # Ordinary module: only the fan-out branch can suppress.
    assert not _is_shared_infra("src/hot.py")
    assert not _is_shared_infra("src/hot.py", fanout=3, fanout_threshold=4)
    assert _is_shared_infra("src/hot.py", fanout=4, fanout_threshold=4)
    # threshold=None disables the derived branch entirely.
    assert not _is_shared_infra("src/hot.py", fanout=99, fanout_threshold=None)


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
