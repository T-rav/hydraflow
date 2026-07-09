"""Unit tests for the CH-4 release evidence-pack compiler (#9732).

Covers the pack directory layout, manifest/audit/ops/index contents, the
named-gaps model (every unlocatable datum is recorded, never silent), the
hash-chained summary record on the ``evidence_packs`` stream, and the
all-gaps behavior when every input is absent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

import subprocess_util
from audit_chain import AuditChain
from evidence_pack import (
    RECORD_TYPE_EVIDENCE_PACK,
    EvidencePackResult,
    compile_evidence_pack,
)
from repro_manifest import (
    CONFIG_SNAPSHOT_ALLOWLIST,
    MANIFEST_SCHEMA,
    render_manifest_block,
)
from tests.helpers import ConfigFactory

RC_BRANCH = "rc/2026-07-08-1200"
RC_PR = 500


def _repro_body_block() -> str:
    return render_manifest_block(
        {"schema": MANIFEST_SCHEMA, "hydraflow_sha": "deadbeef"}
    )


def _rc_detail(
    *,
    body: str | None = None,
    commits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A ``gh pr view`` payload for the RC promotion PR."""
    if body is None:
        body = f"Automated RC promotion.\n\n{_repro_body_block()}"
    if commits is None:
        commits = [
            {
                "oid": "1" * 40,
                "messageHeadline": "feat(x): first change (#101)",
                "authors": [{"login": "agent-a"}],
            },
            {
                "oid": "2" * 40,
                "messageHeadline": "refactor(y): second change (#102)",
                "authors": [{"login": "agent-b"}],
            },
            {
                "oid": "3" * 40,
                "messageHeadline": (
                    f"chore(rc): trigger CI for {RC_BRANCH} promotion PR (#{RC_PR})"
                ),
                "authors": [{"login": "hydra-ops-bot"}],
            },
        ]
    return {
        "number": RC_PR,
        "title": f"Promote {RC_BRANCH} → main",
        "url": f"https://github.com/test-org/test-repo/pull/{RC_PR}",
        "body": body,
        "author": {"login": "hydra-ops-bot"},
        "baseRefName": "main",
        "headRefName": RC_BRANCH,
        "headRefOid": "f" * 40,
        "mergeCommit": {"oid": "e" * 40},
        "mergedAt": "2026-07-08T12:34:56Z",
        "commits": commits,
    }


def _included_detail(number: int, *, req_id: str | None = None) -> dict[str, Any]:
    body = f"Closes #{number - 100}."
    if req_id:
        body += f"\n\nReq-ID: {req_id}"
    return {
        "number": number,
        "title": f"PR {number}",
        "body": body,
        "author": {"login": f"agent-{number}"},
    }


class FakeGh:
    """Fake gh transport dispatching ``gh pr view <n>`` on the PR number."""

    def __init__(self, views: dict[int, Any]) -> None:
        self.views = views
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *cmd: str, **_kwargs: Any) -> str:
        self.calls.append(cmd)
        if cmd[:3] == ("gh", "pr", "view"):
            view = self.views[int(cmd[3])]
            if isinstance(view, Exception):
                raise view
            return json.dumps(view)
        raise AssertionError(f"unexpected gh call: {cmd}")


def _approval(number: int, *, approver: str = "T-rav") -> dict[str, Any]:
    return {
        "schema": 1,
        "record_type": "approval",
        "repo": "test-org/test-repo",
        "pr_number": number,
        "base_branch": "staging",
        "head_branch": f"worktree-issue-{number}",
        "merged_at": "2026-07-08T10:00:00Z",
        "timestamp": datetime.now(UTC).isoformat(),
        "author_identity": f"agent-{number}",
        "approver_identity": approver,
        "role": "operator",
        "role_separated": True,
    }


@pytest.fixture
def config(tmp_path):
    return ConfigFactory.create(repo_root=tmp_path / "repo")


def _default_views() -> dict[int, Any]:
    return {
        RC_PR: _rc_detail(),
        101: _included_detail(101, req_id="SR-42"),
        102: _included_detail(102),
    }


def _install(monkeypatch, views: dict[int, Any]) -> FakeGh:
    fake = FakeGh(views)
    monkeypatch.setattr(subprocess_util, "run_subprocess", fake)
    return fake


def _seed_approvals(config, *numbers: int) -> None:
    chain = AuditChain(config.approval_records_path)
    for number in numbers:
        chain.append(_approval(number))


def _write_audit_report(config, summary: dict[str, int] | None = None) -> None:
    path = config.repo_root / ".hydraflow" / "audit-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "summary": summary
        or {"pass": 40, "warn": 2, "fail": 0, "na": 3, "not_implemented": 1},
        "findings": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


async def _compile(config, **kwargs) -> EvidencePackResult:
    kwargs.setdefault("disabled_workers", set())
    return await compile_evidence_pack(config, RC_BRANCH, RC_PR, **kwargs)


def _pack_file(result: EvidencePackResult, name: str) -> Any:
    text = (result.pack_dir / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


class TestPackLayout:
    @pytest.mark.asyncio
    async def test_pack_dir_is_rc_slug_under_evidence_root(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)

        assert result.pack_dir == config.evidence_dir / "rc-2026-07-08-1200"
        for name in ("manifest.json", "audit.json", "ops.json", "index.md"):
            assert (result.pack_dir / name).is_file(), name

    @pytest.mark.asyncio
    async def test_result_reports_zero_gaps_when_every_datum_present(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)

        assert result.gaps == ()
        assert result.gap_count == 0
        assert result.rc_branch == RC_BRANCH
        assert result.pr_number == RC_PR


class TestManifestJson:
    @pytest.mark.asyncio
    async def test_sha_range_pins_rc_head_and_merge_commit(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        assert manifest["sha_range"] == {
            "base_ref": "main",
            "head_ref": RC_BRANCH,
            "head_sha": "f" * 40,
            "merge_commit_sha": "e" * 40,
        }
        assert manifest["rc_branch"] == RC_BRANCH
        assert manifest["pr_number"] == RC_PR
        assert manifest["repo"] == "test-org/test-repo"

    @pytest.mark.asyncio
    async def test_included_prs_come_from_commit_headlines_minus_rc_itself(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        numbers = [entry["number"] for entry in manifest["included_prs"]]
        assert numbers == [101, 102]  # RC's own synthetic-commit ref excluded

    @pytest.mark.asyncio
    async def test_included_pr_carries_approval_authors_and_req_id(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        entry = next(e for e in manifest["included_prs"] if e["number"] == 101)
        assert entry["approval"]["role"] == "operator"
        assert entry["approval"]["role_separated"] is True
        assert entry["approval"]["approver"] == "T-rav"
        assert entry["authors"] == ["agent-101"]
        assert entry["req_id"] == "SR-42"
        assert manifest["req_ids"] == ["SR-42"]

    @pytest.mark.asyncio
    async def test_rc_repro_manifest_is_parsed_from_the_pr_body(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        assert manifest["repro_manifest"]["schema"] == MANIFEST_SCHEMA
        assert manifest["repro_manifest"]["hydraflow_sha"] == "deadbeef"


class TestNamedGaps:
    @pytest.mark.asyncio
    async def test_missing_approval_record_is_a_named_gap(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101)  # 102 has no approval record
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        entry = next(e for e in manifest["included_prs"] if e["number"] == 102)
        assert entry["approval"] is None
        kinds = [g["kind"] for g in manifest["gaps"]]
        assert "approval_record_missing" in kinds
        gap = next(
            g for g in manifest["gaps"] if g["kind"] == "approval_record_missing"
        )
        assert "102" in gap["detail"]
        assert "102" in _pack_file(result, "index.md")

    @pytest.mark.asyncio
    async def test_rc_body_without_manifest_is_a_named_gap(
        self, config, monkeypatch
    ) -> None:
        views = _default_views()
        views[RC_PR] = _rc_detail(body="No manifest here.")
        _install(monkeypatch, views)
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        assert manifest["repro_manifest"] is None
        assert "repro_manifest_missing" in [g["kind"] for g in manifest["gaps"]]

    @pytest.mark.asyncio
    async def test_absent_audit_report_is_a_named_gap(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)

        result = await _compile(config)

        audit = _pack_file(result, "audit.json")
        assert audit["principles_audit"] is None
        manifest = _pack_file(result, "manifest.json")
        assert "audit_report_missing" in [g["kind"] for g in manifest["gaps"]]

    @pytest.mark.asyncio
    async def test_unreadable_audit_report_is_a_named_gap(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        path = config.repo_root / ".hydraflow" / "audit-report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<<<< not json", encoding="utf-8")

        result = await _compile(config)

        manifest = _pack_file(result, "manifest.json")
        assert "audit_report_unreadable" in [g["kind"] for g in manifest["gaps"]]

    @pytest.mark.asyncio
    async def test_gh_outage_yields_an_all_gaps_pack_not_an_error(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, {RC_PR: RuntimeError("gh: connection refused")})

        result = await _compile(config, disabled_workers=None)

        manifest = _pack_file(result, "manifest.json")
        kinds = [g["kind"] for g in manifest["gaps"]]
        assert "rc_pr_detail_unavailable" in kinds
        assert "repro_manifest_missing" in kinds
        assert "audit_report_missing" in kinds
        assert "approval_stream_missing" in kinds
        assert "loop_states_unavailable" in kinds
        assert manifest["included_prs"] == []
        assert manifest["sha_range"]["head_sha"] == ""
        assert result.gap_count == len(manifest["gaps"])

    @pytest.mark.asyncio
    async def test_included_pr_fetch_failure_is_per_pr_not_fatal(
        self, config, monkeypatch
    ) -> None:
        views = _default_views()
        views[102] = RuntimeError("gh: 502")
        _install(monkeypatch, views)
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        manifest = _pack_file(result, "manifest.json")

        numbers = [entry["number"] for entry in manifest["included_prs"]]
        assert numbers == [101, 102]  # 102 still listed, from commit evidence
        kinds = [g["kind"] for g in manifest["gaps"]]
        assert "included_pr_detail_unavailable" in kinds
        entry = next(e for e in manifest["included_prs"] if e["number"] == 102)
        assert entry["approval"] is not None  # approval evidence is local

    @pytest.mark.asyncio
    async def test_authentication_error_propagates_to_the_caller(
        self, config, monkeypatch
    ) -> None:
        _install(
            monkeypatch,
            {RC_PR: subprocess_util.AuthenticationError("gh: bad credentials")},
        )

        with pytest.raises(subprocess_util.AuthenticationError):
            await _compile(config)


class TestAuditJson:
    @pytest.mark.asyncio
    async def test_principles_totals_parsed_from_audit_report(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config, summary={"pass": 7, "warn": 1, "fail": 0})

        result = await _compile(config)
        audit = _pack_file(result, "audit.json")

        assert audit["principles_audit"]["summary"] == {
            "pass": 7,
            "warn": 1,
            "fail": 0,
        }

    @pytest.mark.asyncio
    async def test_every_registered_stream_is_chain_verified(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        audit = _pack_file(result, "audit.json")

        streams = {entry["stream"]: entry for entry in audit["chain_verification"]}
        assert set(streams) == {
            "preflight",
            "health_decisions",
            "inference_telemetry",
            "approval_records",
            "evidence_packs",
        }
        assert all(entry["ok"] for entry in streams.values())
        assert streams["approval_records"]["chained_records"] == 2

    @pytest.mark.asyncio
    async def test_chain_break_is_reported_and_named_as_a_gap(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)
        # Tamper: flip a byte inside the first record's content.
        path = config.approval_records_path
        path.write_text(
            path.read_text(encoding="utf-8").replace("agent-101", "agent-EVIL"),
            encoding="utf-8",
        )

        result = await _compile(config)

        audit = _pack_file(result, "audit.json")
        broken = next(
            e for e in audit["chain_verification"] if e["stream"] == "approval_records"
        )
        assert broken["ok"] is False
        assert broken["breaks"]
        manifest = _pack_file(result, "manifest.json")
        gap = next(g for g in manifest["gaps"] if g["kind"] == "audit_chain_break")
        assert "approval_records" in gap["detail"]


class TestOpsJson:
    @pytest.mark.asyncio
    async def test_config_snapshot_reuses_the_ch7_allowlist(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        ops = _pack_file(result, "ops.json")

        assert set(ops["config_snapshot"]) == set(CONFIG_SNAPSHOT_ALLOWLIST)
        for name, value in ops["config_snapshot"].items():
            assert value == getattr(config, name)

    @pytest.mark.asyncio
    async def test_disabled_workers_recorded_when_provided(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config, disabled_workers={"sentry", "diagram"})
        ops = _pack_file(result, "ops.json")

        assert ops["loop_states"] == {"disabled_workers": ["diagram", "sentry"]}
        manifest = _pack_file(result, "manifest.json")
        assert manifest["gaps"] == []

    @pytest.mark.asyncio
    async def test_unknown_loop_states_are_a_named_gap(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config, disabled_workers=None)
        ops = _pack_file(result, "ops.json")

        assert ops["loop_states"] is None
        manifest = _pack_file(result, "manifest.json")
        assert "loop_states_unavailable" in [g["kind"] for g in manifest["gaps"]]


class TestIndexMd:
    @pytest.mark.asyncio
    async def test_index_summarizes_rc_and_has_named_gaps_section(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101)
        _write_audit_report(config)

        result = await _compile(config)
        index = _pack_file(result, "index.md")

        assert RC_BRANCH in index
        assert f"#{RC_PR}" in index
        assert "#101" in index
        assert "## Named Gaps" in index
        assert "approval_record_missing" in index

    @pytest.mark.asyncio
    async def test_index_states_no_gaps_when_evidence_is_complete(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)
        index = _pack_file(result, "index.md")

        assert "## Named Gaps" in index
        assert "None — all evidence located." in index


class TestChainRecord:
    @pytest.mark.asyncio
    async def test_summary_record_is_appended_to_the_evidence_packs_stream(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101)
        _write_audit_report(config)

        result = await _compile(config)

        chain = AuditChain(config.evidence_packs_path)
        verified = chain.verify()
        assert verified.ok
        assert verified.chained_records == 1
        line = config.evidence_packs_path.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        assert record["record_type"] == RECORD_TYPE_EVIDENCE_PACK
        assert record["pack_path"] == str(result.pack_dir)
        assert record["pr_number"] == RC_PR
        assert record["rc_branch"] == RC_BRANCH
        assert record["sha_range"]["head_sha"] == "f" * 40
        assert record["gap_count"] == result.gap_count > 0
        assert set(record["files"]) == {
            "manifest.json",
            "audit.json",
            "ops.json",
            "index.md",
        }

    @pytest.mark.asyncio
    async def test_recorded_digests_match_the_written_files(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        result = await _compile(config)

        assert result.chain_record["files"] == result.file_digests
        for name, digest in result.file_digests.items():
            raw = (result.pack_dir / name).read_bytes()
            assert digest == "sha256:" + hashlib.sha256(raw).hexdigest()

    @pytest.mark.asyncio
    async def test_recompiling_the_same_rc_appends_a_second_linked_record(
        self, config, monkeypatch
    ) -> None:
        _install(monkeypatch, _default_views())
        _seed_approvals(config, 101, 102)
        _write_audit_report(config)

        await _compile(config)
        await _compile(config)

        verified = AuditChain(config.evidence_packs_path).verify()
        assert verified.ok
        assert verified.chained_records == 2
