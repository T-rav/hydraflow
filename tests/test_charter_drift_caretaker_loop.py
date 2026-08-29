"""Unit tests for CharterDriftCaretakerLoop (#11748; ADR-0121, ADR-0143)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from charter import (
    CHARTER_FILENAME,
    FINDING_MISSING_ARTIFACT,
    FINDING_MISSING_LAYER,
    FINDING_MISSING_STANDARD,
    FINDING_UNCHECKABLE_CHARTER,
    FINDING_UNKNOWN_LAYER,
    LEGACY_RAILS_FILENAME,
    Articles,
    Artifacts,
    Charter,
    CharterDriftReport,
    CharterError,
    CharterFinding,
    RailsBlock,
    load_charter,
    write_charter,
)
from charter_drift_caretaker_loop import (
    CharterDriftCaretakerLoop,
    _dedup_key,
    audit_repo_charter,
    observe_repo,
    shipped_standard_ids,
)
from dedup_store import DedupStore
from tests.helpers import make_bg_loop_deps

REPO_ROOT = Path(__file__).resolve().parent.parent

_CLEAN = CharterDriftReport(repo="o/r", findings=())
_MISSING_LAYER = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id="missing-layer:language_pack",
            finding_class=FINDING_MISSING_LAYER,
            detail="the 'language_pack' layer is gone",
        ),
    ),
)
_MISSING_STANDARD = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id="missing-standard:testing",
            finding_class=FINDING_MISSING_STANDARD,
            detail="docs/standards/testing/ is absent",
        ),
    ),
)
_UNKNOWN_ONLY = CharterDriftReport(
    repo="o/r",
    findings=(
        CharterFinding(
            check_id="unknown-layer:operator_agent_pack",
            finding_class=FINDING_UNKNOWN_LAYER,
            detail="tolerated future layer",
        ),
    ),
)
_UNGOVERNED = CharterDriftReport(repo="o/r", findings=(), has_charter=False)


def _build(
    tmp_path: Path,
    *,
    reports: list[CharterDriftReport],
    enabled: bool = True,
    loop_enabled: bool = True,
    **overrides,
):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **overrides)
    config = deps.config.model_copy(
        update={"charter_drift_caretaker_loop_enabled": loop_enabled}
    )
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.find_existing_issue = AsyncMock(return_value=0)
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
    dedup = DedupStore("cdc", tmp_path / "cdc.json")
    auditor = AsyncMock(return_value=reports)
    loop = CharterDriftCaretakerLoop(
        config=config,
        pr_manager=pr,
        dedup=dedup,
        deps=deps.loop_deps,
        auditor=auditor,
    )
    return loop, pr, dedup, auditor


async def test_clean_files_no_issue(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    assert await loop._do_work() == {
        "status": "clean",
        "filed": 0,
        "deduped": 0,
        "resolved": 0,
    }
    pr.create_issue.assert_not_awaited()


async def test_drift_files_one_issue_with_check_ids(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    result = await loop._do_work()
    assert result["status"] == "drift"
    assert result["filed"] == 1
    pr.create_issue.assert_awaited_once()
    title, body = pr.create_issue.await_args.args[:2]
    assert "charter-drift" in title
    assert "missing-layer" in title
    assert "missing-layer:language_pack" in body
    assert pr.create_issue.await_args.kwargs["labels"] == [
        "hydraflow-find",
        "hydraflow-charter-drift",
    ]
    assert _dedup_key("o/r", FINDING_MISSING_LAYER) in dedup.get()


async def test_missing_standard_files_its_own_issue(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_STANDARD])
    result = await loop._do_work()
    assert result["filed"] == 1
    assert _dedup_key("o/r", FINDING_MISSING_STANDARD) in dedup.get()


async def test_same_drift_is_deduped(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    await loop._do_work()
    pr.create_issue.reset_mock()
    result = await loop._do_work()
    assert result["deduped"] == 1
    assert result["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_unknown_layer_only_is_not_fatal(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_UNKNOWN_ONLY])
    result = await loop._do_work()
    assert result == {
        "status": "clean",
        "filed": 0,
        "deduped": 0,
        "resolved": 0,
    }
    pr.create_issue.assert_not_awaited()
    assert dedup.get() == set()


async def test_ungoverned_repo_is_skipped(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_UNGOVERNED])
    result = await loop._do_work()
    assert result["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_resolved_drift_closes_issue_and_clears_dedup(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    await loop._do_work()
    assert _dedup_key("o/r", FINDING_MISSING_LAYER) in dedup.get()
    loop._auditor = AsyncMock(return_value=[_CLEAN])
    pr.find_existing_issue = AsyncMock(return_value=4242)
    result = await loop._do_work()
    assert result["resolved"] == 1
    pr.close_issue.assert_awaited_once_with(4242)
    assert dedup.get() == set()


async def test_disabled_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], enabled=False
    )
    assert await loop._do_work() == {"status": "disabled"}
    auditor.assert_not_awaited()


async def test_config_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], loop_enabled=False
    )
    assert await loop._do_work() == {"status": "config_disabled"}
    auditor.assert_not_awaited()


async def test_dry_run_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], dry_run=True
    )
    assert await loop._do_work() is None
    auditor.assert_not_awaited()


async def test_auditor_failure_is_caught(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    loop._auditor = AsyncMock(side_effect=Exception("transient fs failure"))
    assert await loop._do_work() == {"error": True}
    pr.create_issue.assert_not_awaited()


async def test_create_issue_zero_sentinel_not_tracked(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    pr.create_issue = AsyncMock(return_value=0)
    result = await loop._do_work()
    assert result["filed"] == 0
    assert dedup.get() == set()


async def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    assert loop._get_default_interval() == loop._config.charter_drift_caretaker_interval


# --------------------------------------------------------------------------- #
# observe_repo / audit_repo_charter                                            #
# --------------------------------------------------------------------------- #


def _tree(root: Path, *, standards: tuple[str, ...] = ()) -> None:
    (root / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "adr" / "0044-hydraflow-principles.md").write_text("x")
    (root / "pyproject.toml").write_text("x")
    (root / "scripts").mkdir(exist_ok=True)
    for sid in standards:
        (root / "docs" / "standards" / sid).mkdir(parents=True, exist_ok=True)


def test_observe_repo_detects_layers_and_scripts(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / "scripts" / "scan_secrets").write_text("x")
    observed = observe_repo(tmp_path, Charter(), coverage=90.0)
    assert "universal" in observed.present_layers
    assert "language_pack" in observed.present_layers
    assert "scan_secrets" in observed.present_gate_scripts
    assert observed.coverage == 90.0


def test_observe_repo_reads_standard_directories(tmp_path: Path) -> None:
    _tree(tmp_path, standards=("testing",))
    observed = observe_repo(tmp_path, Charter())
    assert observed.present_standards == frozenset({"testing"})


def test_observe_repo_resolves_only_the_declared_artifacts(tmp_path: Path) -> None:
    _tree(tmp_path)
    charter = Charter(artifacts=Artifacts(required=("docs/adr", "docs/nope")))
    observed = observe_repo(tmp_path, charter)
    assert observed.present_artifacts == frozenset({"docs/adr"})


def test_shipped_standard_ids_enumerates_this_checkout() -> None:
    ids = shipped_standard_ids()
    assert ids is not None
    assert "testing" in ids
    assert ids == frozenset(
        p.name for p in (REPO_ROOT / "docs" / "standards").iterdir() if p.is_dir()
    )


def test_audit_repo_charter_ungoverned_when_no_charter(tmp_path: Path) -> None:
    report = audit_repo_charter("o/r", tmp_path)
    assert report.has_charter is False


def test_audit_repo_charter_flags_missing_layer(tmp_path: Path) -> None:
    write_charter(tmp_path, Charter(rails=RailsBlock(layers=("language_pack",))))
    report = audit_repo_charter("o/r", tmp_path)
    assert report.has_charter is True
    assert not report.clean
    assert any(f.finding_class == FINDING_MISSING_LAYER for f in report.findings)


def test_audit_repo_charter_flags_missing_standard(tmp_path: Path) -> None:
    _tree(tmp_path, standards=("ports-and-loops",))
    write_charter(tmp_path, Charter(articles=Articles(standards=("testing",))))
    report = audit_repo_charter("o/r", tmp_path)
    assert any(f.finding_class == FINDING_MISSING_STANDARD for f in report.findings)


def test_audit_repo_charter_flags_missing_artifact(tmp_path: Path) -> None:
    _tree(tmp_path)
    write_charter(tmp_path, Charter(artifacts=Artifacts(required=("docs/nope",))))
    report = audit_repo_charter("o/r", tmp_path)
    assert any(f.finding_class == FINDING_MISSING_ARTIFACT for f in report.findings)


def test_audit_repo_charter_flags_an_empty_declaration(tmp_path: Path) -> None:
    (tmp_path / CHARTER_FILENAME).write_text("schema_version: 1\n")
    report = audit_repo_charter("o/r", tmp_path)
    assert not report.clean
    assert any(
        f.finding_class == FINDING_UNCHECKABLE_CHARTER for f in report.fatal_findings
    )


def test_audit_repo_charter_reads_a_legacy_rails_manifest(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / LEGACY_RAILS_FILENAME).write_text(
        yaml.safe_dump({"template_version": "1", "layers": ["language_pack"]})
    )
    report = audit_repo_charter("o/r", tmp_path)
    assert report.has_charter is True
    assert report.clean


# --------------------------------------------------------------------------- #
# Dogfood + drift mutation: this repo's own charter, and what breaks it        #
# --------------------------------------------------------------------------- #


def test_this_repo_s_own_charter_audits_clean() -> None:
    """HydraFlow carries its own charter and it is true (#11748)."""
    report = audit_repo_charter("T-rav/hydraflow", REPO_ROOT)
    assert report.has_charter is True
    assert report.clean, [f.detail for f in report.fatal_findings]


def _mirror(charter_path: Path, dest: Path) -> Path:
    """A synthetic tree that satisfies the real charter, to mutate against."""
    root = dest / "repo"
    root.mkdir()
    shutil.copy(charter_path, root / CHARTER_FILENAME)
    charter = load_charter(root)
    assert charter is not None
    for sid in charter.articles.standards:
        (root / "docs" / "standards" / sid).mkdir(parents=True, exist_ok=True)
    for art in charter.artifacts.required:
        target = root / art
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True, exist_ok=True)
    (root / "docs" / "adr" / "0044-hydraflow-principles.md").write_text("x")
    (root / "pyproject.toml").write_text("x")
    (root / "scripts").mkdir(exist_ok=True)
    return root


def test_mirror_of_this_repo_s_charter_is_clean(tmp_path: Path) -> None:
    root = _mirror(REPO_ROOT / CHARTER_FILENAME, tmp_path)
    assert audit_repo_charter("o/r", root).clean


def test_removing_a_declared_standard_reddens(tmp_path: Path) -> None:
    root = _mirror(REPO_ROOT / CHARTER_FILENAME, tmp_path)
    shutil.rmtree(root / "docs" / "standards" / "testing")
    report = audit_repo_charter("o/r", root)
    assert not report.clean
    assert {f.finding_class for f in report.fatal_findings} == {
        FINDING_MISSING_STANDARD
    }


def test_removing_a_declared_artifact_reddens(tmp_path: Path) -> None:
    root = _mirror(REPO_ROOT / CHARTER_FILENAME, tmp_path)
    shutil.rmtree(root / "docs" / "arch" / "generated")
    report = audit_repo_charter("o/r", root)
    assert not report.clean
    assert {f.finding_class for f in report.fatal_findings} == {
        FINDING_MISSING_ARTIFACT
    }


def test_emptying_the_declaration_reddens_rather_than_passing(tmp_path: Path) -> None:
    root = _mirror(REPO_ROOT / CHARTER_FILENAME, tmp_path)
    (root / CHARTER_FILENAME).write_text("schema_version: 1\n")
    report = audit_repo_charter("o/r", root)
    assert not report.clean
    assert {f.finding_class for f in report.fatal_findings} == {
        FINDING_UNCHECKABLE_CHARTER
    }


async def test_a_malformed_charter_is_not_swallowed(tmp_path: Path) -> None:
    """A corrupt declaration must surface, not read as a clean tick.

    ``CharterError`` is a ``ValueError``, which ``reraise_on_credit_or_bug``
    classifies as a likely bug — so it escapes ``_do_work`` and the loop
    publishes an error status. That is deliberate: swallowing it would file
    nothing and report ``clean``.
    """
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    loop._auditor = AsyncMock(side_effect=CharterError("charter.yaml is not a mapping"))
    with pytest.raises(CharterError):
        await loop._do_work()
    pr.create_issue.assert_not_awaited()
