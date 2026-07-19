"""Unit tests for policy-as-code merge gates (CH-3, #9731).

Covers the policy loader's strict schema validation, ``classify_change``
(most-restrictive-wins), ``check_merge_allowed`` (the unapproved-merge
binding from the factory-autonomy table), and the feature-gated
``enforce_merge_policy`` seam helper: kill-switch bypass, fail-closed on an
unparseable policy, break-glass override records on the CH-2 approval chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import subprocess_util
from approval_records import (
    APPROVAL_RECORD_SCHEMA_VERSION,
    RECORD_TYPE_BREAK_GLASS,
)
from audit_chain import AuditChain
from merge_policy import (
    AUTONOMY_ACT,
    AUTONOMY_ASK,
    ROLE_OPERATOR,
    ROLE_ORCHESTRATOR_REVIEWER,
    MergeApproval,
    MergePolicyError,
    enforce_merge_policy,
    load_merge_policy,
)
from tests.helpers import ConfigFactory

_PACKAGED_POLICY = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "standards"
    / "factory_autonomy"
    / "policy.yaml"
)

_MINIMAL_POLICY = """\
schema_version: 1
merge_gate:
  unapproved_merge_class: high-blast-radius
  break_glass_label_prefix: "policy-override:"
  escalation: hitl
classes:
  - id: tractable-reversible
    readme_row: "Tractable + reversible"
    autonomy: act
    default: true
    actions: [arch-regen-push]
    paths: []
    labels: []
  - id: high-blast-radius
    readme_row: "High blast radius"
    autonomy: ask
    actions: [merge-unapproved-pr]
    paths: []
    labels: []
    required_approvals:
      count: 1
      roles: [operator, orchestrator-reviewer]
    forbidden_actors: []
    escalation: hitl
"""

_MATCHER_POLICY = """\
schema_version: 1
merge_gate:
  unapproved_merge_class: high-blast-radius
  break_glass_label_prefix: "policy-override:"
  escalation: hitl
classes:
  - id: tractable-reversible
    readme_row: "Tractable + reversible"
    autonomy: act
    default: true
    actions: []
    paths: []
    labels: []
  - id: docs-only
    readme_row: "Docs only"
    autonomy: act
    actions: []
    paths: ["docs/**"]
    labels: []
  - id: high-blast-radius
    readme_row: "High blast radius"
    autonomy: ask
    actions: [merge-unapproved-pr]
    paths: ["src/protected/**"]
    labels: ["needs-operator"]
    required_approvals:
      count: 1
      roles: [operator, orchestrator-reviewer]
    forbidden_actors: []
    escalation: hitl
  - id: operator-only
    readme_row: "Operator only"
    autonomy: ask
    actions: []
    paths: ["src/protected/**"]
    labels: []
    required_approvals:
      count: 2
      roles: [operator]
    forbidden_actors: ["rogue-bot"]
    escalation: hitl
"""


def _write_policy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _reviewer_approval() -> MergeApproval:
    return MergeApproval(
        actor="hydraflow-review-pipeline",
        role=ROLE_ORCHESTRATOR_REVIEWER,
        source="review_phase_verdict",
    )


def _operator_approval(actor: str = "T-rav") -> MergeApproval:
    return MergeApproval(actor=actor, role=ROLE_OPERATOR, source="github_review")


class TestLoadMergePolicy:
    """Strict schema validation of the policy file."""

    def test_packaged_policy_loads_and_encodes_the_three_table_rows(self) -> None:
        policy = load_merge_policy(_PACKAGED_POLICY)
        ids = [entry.id for entry in policy.entries]
        assert ids == [
            "tractable-reversible",
            "high-blast-radius",
            "authorial-scope",
        ]
        assert policy.entry("tractable-reversible").autonomy == AUTONOMY_ACT
        assert policy.entry("tractable-reversible").default is True
        assert policy.entry("high-blast-radius").autonomy == AUTONOMY_ASK
        assert policy.entry("authorial-scope").autonomy == AUTONOMY_ACT
        assert policy.unapproved_merge_class == "high-blast-radius"
        assert policy.break_glass_label_prefix == "policy-override:"

    def test_packaged_policy_v1_has_no_path_or_label_matchers(self) -> None:
        """v1 encodes the table 1:1 — no restrictions beyond the prose."""
        policy = load_merge_policy(_PACKAGED_POLICY)
        assert policy.has_change_matchers is False

    def test_packaged_high_blast_requires_one_operator_or_reviewer(self) -> None:
        entry = load_merge_policy(_PACKAGED_POLICY).entry("high-blast-radius")
        assert entry.required_approvals is not None
        assert entry.required_approvals.count == 1
        assert set(entry.required_approvals.roles) == {
            ROLE_OPERATOR,
            ROLE_ORCHESTRATOR_REVIEWER,
        }
        assert entry.forbidden_actors == ()
        assert entry.escalation == "hitl"
        assert "merge-unapproved-pr" in entry.actions

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(MergePolicyError, match="missing"):
            load_merge_policy(tmp_path / "nope.yaml")

    def test_unparseable_yaml_raises(self, tmp_path: Path) -> None:
        path = _write_policy(tmp_path, "classes: [unclosed\n")
        with pytest.raises(MergePolicyError):
            load_merge_policy(path)

    def test_non_mapping_document_raises(self, tmp_path: Path) -> None:
        path = _write_policy(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(MergePolicyError):
            load_merge_policy(path)

    def test_unknown_top_level_key_raises(self, tmp_path: Path) -> None:
        path = _write_policy(tmp_path, _MINIMAL_POLICY + "surprise: true\n")
        with pytest.raises(MergePolicyError, match="surprise"):
            load_merge_policy(path)

    def test_unknown_entry_key_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace(
            "    actions: [arch-regen-push]",
            "    actions: [arch-regen-push]\n    blast_radius: huge",
        )
        with pytest.raises(MergePolicyError, match="blast_radius"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_bad_schema_version_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace("schema_version: 1", "schema_version: 99")
        with pytest.raises(MergePolicyError, match="schema_version"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_bad_autonomy_value_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace("autonomy: act", "autonomy: yolo")
        with pytest.raises(MergePolicyError, match="autonomy"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_ask_entry_without_required_approvals_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace(
            "    required_approvals:\n      count: 1\n"
            "      roles: [operator, orchestrator-reviewer]\n",
            "",
        )
        with pytest.raises(MergePolicyError, match="required_approvals"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_zero_approval_count_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace("count: 1", "count: 0")
        with pytest.raises(MergePolicyError, match="count"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_unknown_role_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace(
            "roles: [operator, orchestrator-reviewer]", "roles: [ceo]"
        )
        with pytest.raises(MergePolicyError, match="role"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_duplicate_entry_id_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace(
            "id: high-blast-radius", "id: tractable-reversible"
        )
        with pytest.raises(MergePolicyError, match="duplicate"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_missing_default_entry_raises(self, tmp_path: Path) -> None:
        text = _MINIMAL_POLICY.replace("    default: true\n", "")
        with pytest.raises(MergePolicyError, match="default"):
            load_merge_policy(_write_policy(tmp_path, text))

    def test_unapproved_merge_class_must_reference_an_ask_entry(
        self, tmp_path: Path
    ) -> None:
        text = _MINIMAL_POLICY.replace(
            "unapproved_merge_class: high-blast-radius",
            "unapproved_merge_class: tractable-reversible",
        )
        with pytest.raises(MergePolicyError, match="unapproved_merge_class"):
            load_merge_policy(_write_policy(tmp_path, text))


class TestClassifyChange:
    """Path-glob / label classification, most-restrictive-wins."""

    def test_no_match_falls_back_to_default_entry(self, tmp_path: Path) -> None:
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change(["src/app.py"], [])
        assert decision.entry_id == "tractable-reversible"
        assert decision.autonomy == AUTONOMY_ACT
        assert decision.matched == ()

    def test_path_glob_match_selects_entry(self, tmp_path: Path) -> None:
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change(["docs/wiki/index.md"], [])
        assert decision.entry_id == "docs-only"

    def test_double_star_glob_matches_zero_segments(self, tmp_path: Path) -> None:
        """``docs/**`` must also match a file directly under ``docs/``."""
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change(["docs/readme.md"], [])
        assert decision.entry_id == "docs-only"

    def test_label_match_selects_entry(self, tmp_path: Path) -> None:
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change([], ["needs-operator"])
        assert decision.entry_id == "high-blast-radius"
        assert decision.autonomy == AUTONOMY_ASK

    def test_ask_beats_act_on_multiple_matches(self, tmp_path: Path) -> None:
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change(["docs/readme.md"], ["needs-operator"])
        assert decision.autonomy == AUTONOMY_ASK

    def test_stricter_approval_count_wins_between_ask_matches(
        self, tmp_path: Path
    ) -> None:
        """Both ask entries match ``src/protected/**`` — the count=2 one wins."""
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change(["src/protected/keys.py"], [])
        assert decision.entry_id == "operator-only"
        assert decision.required_approvals is not None
        assert decision.required_approvals.count == 2

    def test_matched_records_what_triggered_the_classification(
        self, tmp_path: Path
    ) -> None:
        policy = load_merge_policy(_write_policy(tmp_path, _MATCHER_POLICY))
        decision = policy.classify_change([], ["needs-operator"])
        assert any("needs-operator" in item for item in decision.matched)


class TestCheckMergeAllowed:
    """The unapproved-merge binding + per-entry approval requirements."""

    def _policy(self, tmp_path: Path, text: str = _MINIMAL_POLICY):
        return load_merge_policy(_write_policy(tmp_path, text))

    def test_default_class_with_reviewer_approval_is_allowed(
        self, tmp_path: Path
    ) -> None:
        policy = self._policy(tmp_path)
        decision = policy.classify_change([], [])
        verdict = policy.check_merge_allowed(
            decision,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval()],
        )
        assert verdict.allowed is True
        assert verdict.break_glass is False

    def test_no_approvals_is_the_unapproved_merge_action_and_denies(
        self, tmp_path: Path
    ) -> None:
        """Merging a PR nobody approved IS the high-blast-radius table row."""
        policy = self._policy(tmp_path)
        decision = policy.classify_change([], [])
        verdict = policy.check_merge_allowed(
            decision, actor="hydraflow:post_merge_handler", approvals=[]
        )
        assert verdict.allowed is False
        assert verdict.decision is not None
        assert verdict.decision.entry_id == "high-blast-radius"
        assert verdict.decision.escalation == "hitl"
        assert "merge-unapproved-pr" in verdict.reason

    def test_operator_approval_satisfies_the_unapproved_merge_binding(
        self, tmp_path: Path
    ) -> None:
        policy = self._policy(tmp_path)
        decision = policy.classify_change([], [])
        verdict = policy.check_merge_allowed(
            decision,
            actor="hydraflow:pr_unsticker",
            approvals=[_operator_approval()],
        )
        assert verdict.allowed is True

    def test_ask_class_requires_qualifying_roles(self, tmp_path: Path) -> None:
        """operator-only (count=2, roles=[operator]) rejects a reviewer approval."""
        policy = self._policy(tmp_path, _MATCHER_POLICY)
        decision = policy.classify_change(["src/protected/keys.py"], [])
        verdict = policy.check_merge_allowed(
            decision,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval(), _operator_approval()],
        )
        assert verdict.allowed is False
        assert verdict.decision is not None
        assert verdict.decision.entry_id == "operator-only"

    def test_ask_class_allows_when_role_count_met(self, tmp_path: Path) -> None:
        policy = self._policy(tmp_path, _MATCHER_POLICY)
        decision = policy.classify_change(["src/protected/keys.py"], [])
        verdict = policy.check_merge_allowed(
            decision,
            actor="hydraflow:post_merge_handler",
            approvals=[_operator_approval("T-rav"), _operator_approval("alice")],
        )
        assert verdict.allowed is True

    def test_forbidden_actor_denies_even_with_approvals(self, tmp_path: Path) -> None:
        policy = self._policy(tmp_path, _MATCHER_POLICY)
        decision = policy.classify_change(["src/protected/keys.py"], [])
        verdict = policy.check_merge_allowed(
            decision,
            actor="rogue-bot",
            approvals=[_operator_approval("T-rav"), _operator_approval("alice")],
        )
        assert verdict.allowed is False
        assert "rogue-bot" in verdict.reason


def _gate_config(tmp_path: Path, **kwargs: Any):
    return ConfigFactory.create(repo_root=tmp_path / "repo", **kwargs)


def _repo_policy_path(config) -> Path:
    return config.repo_root / "docs" / "standards" / "factory_autonomy" / "policy.yaml"


def _install_repo_policy(config, text: str = _MINIMAL_POLICY) -> Path:
    path = _repo_policy_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fake_label_fetch(monkeypatch, labels: list[str]) -> list[tuple[str, ...]]:
    """Fake the gh transport used for fresh PR-label reads (definition site)."""
    calls: list[tuple[str, ...]] = []

    async def _run(*cmd: str, **_kwargs: Any) -> str:
        calls.append(cmd)
        assert cmd[:3] == ("gh", "pr", "view")
        return json.dumps({"labels": [{"name": name} for name in labels]})

    monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
    return calls


class TestEnforceMergePolicy:
    """The feature-gated seam helper."""

    async def test_kill_switch_bypasses_the_gate(self, tmp_path: Path) -> None:
        config = _gate_config(tmp_path, merge_policy_enabled=False)
        prs = MagicMock()
        verdict = await enforce_merge_policy(
            config=config,
            prs=prs,
            pr_number=7,
            actor="hydraflow:post_merge_handler",
            approvals=[],
            lane="test",
        )
        assert verdict.allowed is True
        assert "disabled" in verdict.reason

    async def test_allow_path_makes_no_port_or_gh_calls(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """v1 default policy has no matchers — an approved merge is O(0) I/O."""
        config = _gate_config(tmp_path)
        _install_repo_policy(config)
        calls = _fake_label_fetch(monkeypatch, [])
        prs = MagicMock()
        prs.get_pr_diff_names = AsyncMock()
        verdict = await enforce_merge_policy(
            config=config,
            prs=prs,
            pr_number=7,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval()],
            lane="post_merge_handler",
        )
        assert verdict.allowed is True
        prs.get_pr_diff_names.assert_not_awaited()
        assert calls == []

    async def test_deny_blocks_and_reports_the_policy_entry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _gate_config(tmp_path)
        _install_repo_policy(config)
        _fake_label_fetch(monkeypatch, ["enhancement"])
        verdict = await enforce_merge_policy(
            config=config,
            prs=MagicMock(),
            pr_number=7,
            actor="hydraflow:pr_unsticker",
            approvals=[],
            lane="pr_unsticker",
        )
        assert verdict.allowed is False
        assert verdict.decision is not None
        assert verdict.decision.entry_id == "high-blast-radius"

    async def test_break_glass_label_allows_and_chains_a_record(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _gate_config(tmp_path)
        _install_repo_policy(config)
        _fake_label_fetch(monkeypatch, ["policy-override:emergency-hotfix"])
        verdict = await enforce_merge_policy(
            config=config,
            prs=MagicMock(),
            pr_number=7,
            actor="hydraflow:pr_unsticker",
            approvals=[],
            lane="pr_unsticker",
        )
        assert verdict.allowed is True
        assert verdict.break_glass is True
        assert verdict.break_glass_label == "policy-override:emergency-hotfix"

        records = [
            json.loads(line)
            for line in config.approval_records_path.read_text().splitlines()
        ]
        assert len(records) == 1
        record = records[0]
        assert record["schema"] == APPROVAL_RECORD_SCHEMA_VERSION
        assert record["record_type"] == RECORD_TYPE_BREAK_GLASS
        assert record["pr_number"] == 7
        assert record["lane"] == "pr_unsticker"
        assert record["actor"] == "hydraflow:pr_unsticker"
        assert record["override_label"] == "policy-override:emergency-hotfix"
        assert record["reason_slug"] == "emergency-hotfix"
        assert record["policy_entry"] == "high-blast-radius"
        assert record["denied_reason"]
        assert AuditChain(config.approval_records_path).verify().ok

    async def test_bare_prefix_label_is_not_a_break_glass(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """``policy-override:`` with no reason slug does not override."""
        config = _gate_config(tmp_path)
        _install_repo_policy(config)
        _fake_label_fetch(monkeypatch, ["policy-override:"])
        verdict = await enforce_merge_policy(
            config=config,
            prs=MagicMock(),
            pr_number=7,
            actor="hydraflow:pr_unsticker",
            approvals=[],
            lane="pr_unsticker",
        )
        assert verdict.allowed is False

    async def test_unparseable_policy_fails_closed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        config = _gate_config(tmp_path)
        path = _repo_policy_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<<<<<<< stash conflict marker\n", encoding="utf-8")
        _fake_label_fetch(monkeypatch, [])
        verdict = await enforce_merge_policy(
            config=config,
            prs=MagicMock(),
            pr_number=7,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval()],
            lane="post_merge_handler",
        )
        assert verdict.allowed is False
        assert "closed" in verdict.reason

    async def test_unparseable_policy_still_honors_break_glass(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Break-glass must work even when the policy file is corrupt."""
        config = _gate_config(tmp_path)
        path = _repo_policy_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<<<<<<< stash conflict marker\n", encoding="utf-8")
        _fake_label_fetch(monkeypatch, ["policy-override:policy-file-corrupt"])
        verdict = await enforce_merge_policy(
            config=config,
            prs=MagicMock(),
            pr_number=7,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval()],
            lane="post_merge_handler",
        )
        assert verdict.allowed is True
        assert verdict.break_glass is True
        assert AuditChain(config.approval_records_path).verify().ok

    async def test_tightened_policy_fetches_paths_and_labels_and_denies(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """An operator-tightened ask entry bites through the real seam inputs."""
        config = _gate_config(tmp_path)
        _install_repo_policy(config, _MATCHER_POLICY)
        _fake_label_fetch(monkeypatch, ["enhancement"])
        prs = MagicMock()
        prs.get_pr_diff_names = AsyncMock(return_value=["src/protected/keys.py"])
        verdict = await enforce_merge_policy(
            config=config,
            prs=prs,
            pr_number=7,
            actor="hydraflow:post_merge_handler",
            approvals=[_reviewer_approval()],
            lane="post_merge_handler",
        )
        assert verdict.allowed is False
        assert verdict.decision is not None
        assert verdict.decision.entry_id == "operator-only"
        prs.get_pr_diff_names.assert_awaited_once_with(7)
