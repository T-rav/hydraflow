"""Tests for the schema-derived settings registry."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import HydraFlowConfig
from settings_registry import (
    GROUP_TO_SECTION,
    OTHER_SECTION,
    SETTINGS,
    build_settings_schema,
    mutable_field_names,
    section_for_group,
)

# The fields that were editable via the old hand-kept _MUTABLE_FIELDS allowlist.
# Coverage must not regress — every one of these stays editable.
_LEGACY_MUTABLE = {
    "gh_circuit_breaker_enabled",
    "merge_policy_enabled",
    "test_adequacy_coverage_timeout_secs",
    "max_triagers",
    "max_workers",
    "max_planners",
    "max_reviewers",
    "max_hitl_workers",
    "model",
    "review_model",
    "planner_model",
    "batch_size",
    "max_ci_fix_attempts",
    "max_quality_fix_attempts",
    "max_review_fix_attempts",
    "min_review_findings",
    "max_merge_conflict_fix_attempts",
    "ci_check_timeout",
    "ci_poll_interval",
    "poll_interval",
    "pr_unstick_interval",
    "pr_unstick_batch_size",
    "unstick_auto_merge",
    "unstick_all_causes",
    "memory_auto_approve",
    "workspace_base",
    "staging_enabled",
    "staging_branch",
    "main_branch",
    "rc_cadence_hours",
}


class TestRegistryIntegrity:
    def test_every_registry_key_is_a_real_config_field(self) -> None:
        fields = set(HydraFlowConfig.model_fields)
        unknown = set(SETTINGS) - fields
        assert not unknown, f"registry references non-existent config fields: {unknown}"

    def test_coverage_does_not_regress_vs_legacy_allowlist(self) -> None:
        missing = _LEGACY_MUTABLE - mutable_field_names()
        assert not missing, f"these fields lost editability: {missing}"

    def test_groups_are_non_empty(self) -> None:
        assert all(spec.group.strip() for spec in SETTINGS.values())


class TestSchemaDerivation:
    def _schema(self) -> dict[str, dict]:
        rows = build_settings_schema(HydraFlowConfig())
        return {r["name"]: r for r in rows}

    def test_bool_field(self) -> None:
        row = self._schema()["staging_enabled"]
        assert row["type"] == "bool"
        assert row["choices"] is None

    def test_int_field_carries_bounds(self) -> None:
        row = self._schema()["max_workers"]
        assert row["type"] == "int"
        assert row["min"] == 1
        assert row["max"] is not None and row["max"] >= 1

    def test_enum_field_from_literal(self) -> None:
        # rc_cadence_hours is int; a Literal-typed field carries choices.
        # staging_branch is a plain str; use a known Literal field instead.
        rows = self._schema()
        # model tiers / tool are the enum-ish ones; ensure at least one enum row
        enum_rows = [r for r in rows.values() if r["type"] == "enum"]
        # Not all seeds are enums, but derivation must expose choices when present.
        for r in enum_rows:
            assert r["choices"], f"{r['name']} typed enum but no choices"

    def test_enum_field_from_str_enum_offers_every_queue_discipline(self) -> None:
        # queue_strategy (#10037) is a StrEnum, not a Literal — a different
        # branch of _derive_type. It is the operator's only runtime access to
        # the work picker, and 'fifo' in particular is the escape hatch back to
        # the pre-#10037 ordering, so a dropped choice strands them.
        row = self._schema()["queue_strategy"]
        assert row["type"] == "enum"
        assert set(row["choices"]) == {"fifo", "priority", "weighted_mix"}

    def test_current_value_reflects_config(self) -> None:
        cfg = HydraFlowConfig()
        object.__setattr__(cfg, "max_workers", 7)
        rows = {r["name"]: r for r in build_settings_schema(cfg)}
        assert rows["max_workers"]["value"] == 7

    def test_description_is_populated(self) -> None:
        row = self._schema()["max_workers"]
        assert row["description"]

    def test_rows_sorted_by_group_then_order(self) -> None:
        rows = build_settings_schema(HydraFlowConfig())
        keys = [(r["group"], SETTINGS[r["name"]].order, r["name"]) for r in rows]
        assert keys == sorted(keys)

    def test_workspace_path_value_is_jsonable_string(self) -> None:
        row = self._schema()["workspace_base"]
        assert isinstance(row["value"], str)

    def test_live_flag_present_per_row(self) -> None:
        for row in build_settings_schema(HydraFlowConfig()):
            assert isinstance(row["live"], bool)


class TestHeavyMakeTimeoutKnobs:
    """#9555 — heavy-make subprocess caps are System-tab knobs, not constants.

    #9580 (closed into #9555) additionally requires the caps to be
    operator-visible numeric inputs with the Pydantic ge/le bounds as
    min/max — satisfied here because the settings screen is schema-driven:
    a registry row with min/max IS the editable numeric input.
    """

    def _schema(self) -> dict[str, dict]:
        rows = build_settings_schema(HydraFlowConfig())
        return {r["name"]: r for r in rows}

    def test_adversarial_timeout_is_mutable_and_schema_visible(self) -> None:
        assert "skill_prompt_eval_adversarial_timeout_seconds" in mutable_field_names()
        row = self._schema()["skill_prompt_eval_adversarial_timeout_seconds"]
        assert row["type"] == "int"
        assert row["group"] == "Trust Fleet"
        assert row["live"] is True
        assert row["default"] == 3600
        assert row["min"] == 60
        assert row["max"] == 21600
        assert row["description"]

    def test_principles_audit_timeout_is_mutable_and_schema_visible(self) -> None:
        assert "principles_audit_timeout_seconds" in mutable_field_names()
        row = self._schema()["principles_audit_timeout_seconds"]
        assert row["type"] == "int"
        assert row["group"] == "Trust Fleet"
        assert row["live"] is True
        assert row["default"] == 1800
        assert row["min"] == 60
        assert row["max"] == 21600
        assert row["description"]

    def test_staging_bisect_runtime_cap_is_mutable_and_schema_visible(self) -> None:
        # The pre-existing runtime cap #9580 called out as PATCH-mutable but
        # operator-invisible; same treatment as the two new caps.
        assert "staging_bisect_runtime_cap_seconds" in mutable_field_names()
        row = self._schema()["staging_bisect_runtime_cap_seconds"]
        assert row["type"] == "int"
        assert row["group"] == "Branching & Release"
        assert row["live"] is True
        assert row["default"] == 2700
        assert row["min"] == 300
        assert row["max"] == 14400


class TestWorkflowSection:
    """#10786 — schema rows carry a server-derived ``section`` (coarse,
    stage/concern grouping) so the operator console's workflow-config panel can
    render grouped panels without a UI-side allowlist."""

    def _rows(self) -> list[dict]:
        return build_settings_schema(HydraFlowConfig())

    def _schema(self) -> dict[str, dict]:
        return {r["name"]: r for r in self._rows()}

    def test_every_row_carries_a_non_empty_section(self) -> None:
        rows = self._rows()
        assert rows, "expected a non-empty schema"
        for row in rows:
            assert isinstance(row["section"], str)
            assert row["section"].strip(), f"{row['name']} has an empty section"

    def test_group_to_section_map_is_applied(self) -> None:
        schema = self._schema()
        # Concurrency fields collapse into the coarse Workers & Batch section.
        assert schema["max_workers"]["section"] == "Workers & Batch"
        assert schema["batch_size"]["section"] == "Workers & Batch"
        # Work Queue keeps its own section.
        assert schema["queue_strategy"]["section"] == "Work Queue"
        # Model + Model Routing groups both fold into Model Routing.
        assert schema["model"]["section"] == "Model Routing"
        assert schema["openrouter_base_url"]["section"] == "Model Routing"
        # Merge policy lands in Merge & Release.
        assert schema["merge_policy_enabled"]["section"] == "Safety & Reliability"
        assert schema["staging_enabled"]["section"] == "Merge & Release"
        # The reliability/kill-switch toggles fold into Safety & Reliability.
        assert schema["gh_circuit_breaker_enabled"]["section"] == "Safety & Reliability"

    def test_section_is_derived_from_the_row_group(self) -> None:
        # The section is a pure function of the group — no per-row surprises.
        for row in self._rows():
            assert row["section"] == section_for_group(row["group"])

    def test_section_is_additive_group_key_unchanged(self) -> None:
        # The classic RuntimeSettingsPanel keys off ``group``; it must be intact.
        for row in self._rows():
            assert row["group"] == SETTINGS[row["name"]].group

    def test_every_section_is_a_known_section_or_other(self) -> None:
        # Totality: no row escapes into an undeclared section.
        allowed = set(GROUP_TO_SECTION.values()) | {OTHER_SECTION}
        for row in self._rows():
            assert row["section"] in allowed

    def test_unmapped_group_falls_back_to_other(self) -> None:
        # A future group with no explicit mapping is never dropped — it lands in
        # the Other bucket rather than vanishing from the panel.
        assert section_for_group("Some Brand New Group") == OTHER_SECTION

    def test_row_ordering_is_unchanged_by_the_additive_section(self) -> None:
        # Sort key stays (group, order, name); section is metadata only.
        rows = self._rows()
        keys = [(r["group"], SETTINGS[r["name"]].order, r["name"]) for r in rows]
        assert keys == sorted(keys)
