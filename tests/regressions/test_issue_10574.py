"""Regression: escape ledger has no operator path to record a human resolution (#10574).

``EscapeLedger.append_resolution`` (the sanctioned way for a human to close out
a HITL escape by naming its encoding) existed but had ZERO non-test callers — no
CLI, no dashboard action, no loop path. Every ``escape-ledger`` HITL issue asked
a human to "point at the encoding" with no mechanism to record the answer, so
``encoded_as`` stayed ``none-yet`` forever and the aging surface re-fired.

This pins the operator trigger surface added by #10574:

* the pure ``escape.resolve`` service (``resolve_escape`` / ``list_unresolved`` /
  ``default_ledger_path``) that wraps the orphaned ``append_resolution``;
* the ``scripts/resolve_escape.py`` CLI that operators actually invoke, including
  the DEFAULT ledger-path resolution when ``--ledger-path`` is omitted; and
* the end-to-end promise the issue makes: an operator recording a resolution
  feeds ``EscapeLedgerLoop._reconcile_surfaced_issues`` (#10577), which then
  closes the stranded HITL issue.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from escape.ledger import ESCAPE_LEDGER_FILENAME, EscapeLedger
from escape.models import EscapeRecord
from escape.resolve import (
    InvalidEncodingError,
    UnknownEscapeIdError,
    default_ledger_path,
    list_unresolved,
    resolve_escape,
)
from escape.surfaces import SurfacedIssueLedger
from escape_ledger_loop import EscapeLedgerLoop
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_bg_loop_deps

_CLI_PATH = Path(__file__).resolve().parents[2] / "scripts" / "resolve_escape.py"


def _load_cli() -> Any:
    spec = importlib.util.spec_from_file_location("resolve_escape_cli", _CLI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["resolve_escape_cli"] = module
    spec.loader.exec_module(module)
    return module


def _record(
    rid: str, *, confidence: str = "low", encoded_as: str = "none-yet"
) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-02T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=24.0,
        attribution_method="fixes-chain",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes="",
    )


def _build_loop(tmp_path: Path, github: FakeGitHub) -> EscapeLedgerLoop:
    """A loop wired to a real FakeGitHub, no git repo needed (reconcile is git-free)."""
    from unittest.mock import MagicMock

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    state = MagicMock()
    state.get_escape_ledger_last_processed_sha.return_value = ""
    dedup_store: set[str] = set()
    dedup = MagicMock()
    dedup.get.side_effect = lambda: set(dedup_store)
    dedup.set_all.side_effect = lambda values: (
        dedup_store.clear() or dedup_store.update(values)
    )
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=dedup,
        deps=bg.loop_deps,
    )


class TestOperatorResolutionFeedsReconcile:
    async def test_operator_resolution_closes_the_stranded_hitl_issue(
        self, tmp_path: Path
    ) -> None:
        # Arrange: an aging, unencoded escape gets surfaced as a HITL issue.
        github = FakeGitHub()
        loop = _build_loop(tmp_path, github)
        ledger = EscapeLedger(loop._ledger_path)
        ledger.append(_record("bug-issue:a", confidence="high", encoded_as="none-yet"))
        await loop._surface_findings()
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()
        issue_number = link.issue_number

        # Act: an operator records the resolution via the new service path.
        recorded = resolve_escape(
            "bug-issue:a",
            "regression-test",
            ledger_path=loop._ledger_path,
            notes="pinned by tests/regressions/test_x.py",
        )

        # Assert: append_resolution was invoked (a superseding row now wins) ...
        assert recorded.encoded_as == "regression-test"
        assert EscapeLedger(loop._ledger_path).read_latest()[0].encoded_as == (
            "regression-test"
        )
        # ... and reconcile can now close the stranded HITL issue.
        assert await loop._reconcile_surfaced_issues() == 1
        assert github._issues[issue_number].state == "closed"

    def test_hitl_finding_body_names_the_resolve_command(self) -> None:
        # The issue's core complaint: findings asked a human to "point at the
        # encoding" with no mechanism. The body must now name the operator CLI.
        from escape_ledger_loop import SURFACE_REASON_AGING, _render_finding

        _title, body = _render_finding(
            _record("bug-issue:a", encoded_as="none-yet"), SURFACE_REASON_AGING
        )
        assert "make escape-resolve" in body
        assert "--encoded-as" in body
        assert "bug-issue:a" in body


class TestResolveEscapeService:
    def test_default_ledger_path_uses_config_diagnostics_dir(
        self, tmp_path: Path
    ) -> None:
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        assert default_ledger_path(bg.config) == (
            bg.config.diagnostics_dir / ESCAPE_LEDGER_FILENAME
        )

    def test_resolve_escape_rejects_none_yet_sentinel(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        EscapeLedger(ledger_path).append(_record("bug-issue:a"))
        with pytest.raises(InvalidEncodingError):
            resolve_escape("bug-issue:a", "none-yet", ledger_path=ledger_path)

    def test_resolve_escape_rejects_unknown_encoding(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        EscapeLedger(ledger_path).append(_record("bug-issue:a"))
        with pytest.raises(InvalidEncodingError):
            resolve_escape("bug-issue:a", "nonsense", ledger_path=ledger_path)

    def test_resolve_escape_unknown_id_raises(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        EscapeLedger(ledger_path).append(_record("bug-issue:a"))
        with pytest.raises(UnknownEscapeIdError):
            resolve_escape("bug-issue:missing", "detector", ledger_path=ledger_path)

    def test_list_unresolved_returns_only_none_yet_rows(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        ledger = EscapeLedger(ledger_path)
        ledger.append(_record("bug-issue:a", encoded_as="none-yet"))
        ledger.append(_record("bug-issue:b", encoded_as="detector"))
        unresolved = list_unresolved(ledger_path)
        assert [r.id for r in unresolved] == ["bug-issue:a"]


class TestResolveEscapeCli:
    def test_cli_resolve_records_resolution_row(self, tmp_path: Path) -> None:
        cli = _load_cli()
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        EscapeLedger(ledger_path).append(_record("bug-issue:a"))

        rc = cli.main(
            [
                "resolve",
                "bug-issue:a",
                "--encoded-as",
                "adr",
                "--confidence",
                "high",
                "--notes",
                "ADR-0060 covers this",
                "--ledger-path",
                str(ledger_path),
            ]
        )

        assert rc == 0
        latest = EscapeLedger(ledger_path).read_latest()[0]
        assert latest.encoded_as == "adr"
        assert latest.attribution_confidence == "high"
        assert latest.notes == "ADR-0060 covers this"

    def test_cli_unknown_id_returns_nonzero(self, tmp_path: Path) -> None:
        cli = _load_cli()
        ledger_path = tmp_path / ESCAPE_LEDGER_FILENAME
        EscapeLedger(ledger_path).append(_record("bug-issue:a"))
        rc = cli.main(
            ["resolve", "nope", "--encoded-as", "detector", "--ledger-path", str(ledger_path)]
        )
        assert rc != 0

    def test_cli_list_uses_default_ledger_path_when_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The missing-default-path-test gap that failed prior attempts: exercise
        # the CLI branch that resolves the ledger path from config when
        # --ledger-path is omitted, end to end.
        cli = _load_cli()
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        default_path = default_ledger_path(bg.config)
        EscapeLedger(default_path).append(_record("bug-issue:a", encoded_as="none-yet"))
        monkeypatch.setattr(cli, "HydraFlowConfig", lambda: bg.config)

        rc = cli.main(["list"])

        assert rc == 0
