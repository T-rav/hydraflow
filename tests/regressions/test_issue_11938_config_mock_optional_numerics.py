"""#11938 — `config_mock()` left every Optional-numeric config field a Mock.

Upheld sampled re-audit of PR #11909 (`d96282d13a15`). The helper decided
"numeric" by asking ``field.annotation in (int, float)``, which is a spelling
test. ``float | None`` is a ``types.UnionType`` and equals neither member, so
all ten Optional-numeric knobs were skipped — and that is the newest and
fastest-growing shape in the config (all five ``audit_retention_days_*`` use
it).

Skipping them was worse than never having seeded anything. Production guards
those fields with ``if threshold is None: return``; a Mock is not ``None``, the
guard silently does not fire, and execution falls through to a comparison
against a Mock — the exact ``TypeError`` (#11827) the helper was built to
eliminate. The converted call sites only escaped by overriding those fields by
hand, so the helper's advertised guarantee was false while every test was green.

The guard below derives its subject from ``model_fields`` **textually**, while
the fix walks the annotation **structurally**. Two independent routes to the
same question on purpose: a future shape that escapes the walk (a new wrapper,
a nested alias) still reddens here, because both would have to be wrong in the
same way to stay silent.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from config import HydraFlowConfig
from tests.helpers import config_mock

#: Matches an annotation whose text mentions a number type anywhere — under a
#: union, an Annotated wrapper, or a nesting none of us has thought of. Reads
#: `str(annotation)`, never the type structure, so it cannot inherit a bug from
#: the predicate it is checking.
_MENTIONS_A_NUMBER = re.compile(r"\b(?:int|float)\b")


def _numeric_bearing_fields() -> list[str]:
    return [
        name
        for name, field in HydraFlowConfig.model_fields.items()
        if _MENTIONS_A_NUMBER.search(str(field.annotation))
    ]


def test_the_sweep_finds_its_own_subject() -> None:
    """A guard over an empty field list passes silently and reads as coverage."""
    fields = _numeric_bearing_fields()

    assert len(fields) > 100, f"only {len(fields)} numeric-bearing fields found"


def test_no_numeric_bearing_field_is_left_a_mock() -> None:
    mock = config_mock()

    escaped = [
        name
        for name in _numeric_bearing_fields()
        if isinstance(getattr(mock, name), MagicMock)
    ]

    assert not escaped, (
        f"config_mock() left {len(escaped)} numeric-bearing field(s) as Mocks: "
        f"{escaped[:10]}. Production compares these, and comparison against a "
        "Mock raises; worse, an Optional one defaults to None and is guarded "
        "with `is None`, which a Mock silently passes."
    )


class TestTheOptionalFieldsFromTheAudit:
    """The ten the spelling test missed, by name, because they are the receipt."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "daily_cost_budget_usd",
            "issue_cost_alert_usd",
            "auto_agent_cost_cap_usd",
            "auto_agent_wall_clock_cap_s",
            "auto_agent_daily_budget_usd",
            "audit_retention_days_preflight",
            "audit_retention_days_health_decisions",
            "audit_retention_days_inference_telemetry",
            "audit_retention_days_approval_records",
            "audit_retention_days_evidence_packs",
        ],
    )
    def test_the_optional_default_is_seeded_not_mocked(self, field_name: str) -> None:
        value = getattr(config_mock(), field_name)

        assert value is HydraFlowConfig.model_fields[field_name].default

    def test_an_is_none_guard_short_circuits_as_production_expects(self) -> None:
        # The failure in full: the guard does not fire, so the next line runs.
        threshold = config_mock().daily_cost_budget_usd

        assert threshold is None

    def test_a_comparison_past_the_guard_would_have_raised(self) -> None:
        # Why the above matters. This is the #11827 TypeError, reproduced
        # against a bare Mock so the pin states the consequence rather than
        # trusting the prose.
        with pytest.raises(TypeError):
            _ = 12.0 >= MagicMock()


class TestOverridesStillWin:
    def test_an_override_beats_the_seeded_default(self) -> None:
        assert config_mock(daily_cost_budget_usd=5.0).daily_cost_budget_usd == 5.0

    @pytest.mark.parametrize(
        "field_name",
        [
            pytest.param("repo", id="str"),
            pytest.param("github_host", id="str-with-value"),
            pytest.param("origin_guard_fail_closed", id="bool"),
            pytest.param("ready_label", id="list"),
            pytest.param("queue_strategy", id="enum"),
        ],
    )
    def test_a_non_numeric_field_is_still_an_ordinary_mock(
        self, field_name: str
    ) -> None:
        """The decoy — and it must be a real MODEL FIELD to be one.

        The first version of this asserted on ``config.data_path``, which is a
        method rather than a field, so "seed every field regardless of type"
        passed it vacuously. A mutation run caught that; the parameters here
        are the field shapes such an over-correction would actually change,
        taken from ``model_fields`` rather than imagined.

        Widening past numerics is not free: 79 call sites rely on Mock
        stand-ins, and turning `repo` into `''` or an enum into a real member
        changes what those tests exercise without any of them being edited.
        """
        assert isinstance(getattr(config_mock(), field_name), MagicMock)
