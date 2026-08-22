"""Tests for dx/hydraflow/config.py — Env var overrides."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

# conftest.py already inserts the hydraflow package directory into sys.path
from config import (
    _DEPRECATED_ENV_ALIASES,
    _ENV_BOOL_OVERRIDES,
    _ENV_COMBO_OVERRIDES,
    _ENV_ENUM_OVERRIDES,
    _ENV_FLOAT_OVERRIDES,
    _ENV_FLOAT_RATIO_OVERRIDES,
    _ENV_INT_OVERRIDES,
    _ENV_LITERAL_OVERRIDES,
    _ENV_OPT_FLOAT_OVERRIDES,
    _ENV_OPT_INT_OVERRIDES,
    _ENV_STR_OVERRIDES,
    GATEWAY_CAPABLE_PROVIDER_FIELDS,
    HydraFlowConfig,
    declared_default_config,
    declared_env_keys,
    env_override_keys,
)
from queue_strategy import QueueStrategy

# ---------------------------------------------------------------------------
# Data-driven env-var override table validation
# ---------------------------------------------------------------------------


class TestEnvVarOverrideTable:
    @staticmethod
    def _dependent_values(field: str, *, enabled: bool) -> dict[str, object]:
        if field == "gateway_capture_bodies" and enabled:
            return {"gateway_repo_class": "hydraflow"}
        if field == "gateway_fleet_ratchet_enabled" and enabled:
            values: dict[str, object] = dict.fromkeys(
                GATEWAY_CAPABLE_PROVIDER_FIELDS, "gateway"
            )
            values["execution_mode"] = "docker"
            return values
        return {}

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Each int override should apply when the field is at its default."""
        override_value = default + 1
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == override_value

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Explicit values should take precedence over env var overrides."""
        # Use default + 1 to stay within Pydantic field constraints
        explicit = default + 1
        monkeypatch.setenv(env_key, str(default + 2))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Non-numeric env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == default

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Each str override should apply when the field is at its default."""
        override = self._VALID_VALUES.get(field, "custom-value")
        monkeypatch.setenv(env_key, override)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        result = getattr(cfg, field)
        assert str(result) == override

    # Fields whose value is constrained (a Literal, or a validated grammar), so
    # the generic tests cannot feed them an arbitrary string.
    _VALID_VALUES: dict[str, str] = {
        "gateway_repo_class": "client",
        # ADR-0141 refuses anything that is not an exact canonical owner/repo,
        # because a value that silently arms nothing is worse than an error.
        "gateway_enforcement_canary_repo": "acme/project-x",
    }

    # Valid non-default explicit values for Literal-typed string fields.
    # Generic tests can't use arbitrary strings for these fields.
    _EXPLICIT_VALUES: dict[str, str] = {
        "execution_mode": "docker",
        "gateway_repo_class": "hydraflow",
        "gateway_enforcement_canary_repo": "acme/other-project",
        "security_patch_severity_threshold": "critical",
    }

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Explicit values should take precedence over str env var overrides."""
        explicit = self._EXPLICIT_VALUES.get(field, "explicit-value")
        env_value = self._VALID_VALUES.get(field, "env-value")
        monkeypatch.setenv(env_key, env_value)
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert str(getattr(cfg, field)) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Each float override should apply when the field is at its default."""
        override_value = default + 1.0
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(override_value)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Explicit values should take precedence over float env var overrides."""
        explicit = default + 0.5
        monkeypatch.setenv(env_key, str(default + 1.0))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(explicit)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Non-numeric float env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(default)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Each bool override should apply when the field is at its default."""
        monkeypatch.setenv(env_key, "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is False

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_truthy_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """ADR-0110: bool overrides, including the gateway ratchet, accept truthy values."""
        for truthy in ("1", "true", "yes", "True", "YES"):
            monkeypatch.setenv(env_key, truthy)
            cfg = HydraFlowConfig(
                **self._dependent_values(field, enabled=True),  # type: ignore[arg-type]
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is True, f"'{truthy}' should parse as True"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_falsy_variants(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Bool overrides should treat '0', 'false', 'no' as False."""
        for falsy in ("0", "false", "no", "False", "NO"):
            monkeypatch.setenv(env_key, falsy)
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is False, f"'{falsy}' should parse as False"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Explicit values should take precedence over bool env var overrides."""
        explicit = not default
        monkeypatch.setenv(
            env_key, str(default).lower()
        )  # env tries to revert to default
        cfg = HydraFlowConfig(
            **self._dependent_values(field, enabled=explicit),  # type: ignore[arg-type]
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is explicit

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Each Literal override should apply when the field is at its default."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        # Pick a non-default value from the allowed values
        non_default = next(v for v in allowed if v != default)
        monkeypatch.setenv(env_key, non_default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Explicit values should take precedence over Literal env var overrides."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        non_default = next(v for v in allowed if v != default)
        # Pass non-default explicitly, set env var to default
        monkeypatch.setenv(env_key, default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            **{field: non_default},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        field: str,
        env_key: str,
    ) -> None:
        """Invalid Literal env var values should be rejected and field stays at default."""
        default = HydraFlowConfig.model_fields[field].default
        monkeypatch.setenv(env_key, "bogus")
        with caplog.at_level(logging.WARNING, logger="hydraflow.config"):
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        assert getattr(cfg, field) == default
        assert env_key in caplog.text, "Expected warning to name the invalid env var"
        assert "bogus" in caplog.text, "Expected warning to include the invalid value"

    def test_override_table_field_names_are_valid(self) -> None:
        """Every field in the override tables should be a real HydraFlowConfig attribute."""
        all_fields = (
            {f for f, _, _ in _ENV_INT_OVERRIDES}
            | {f for f, _, _ in _ENV_STR_OVERRIDES}
            | {f for f, _, _ in _ENV_FLOAT_OVERRIDES}
            | {f for f, _, _ in _ENV_BOOL_OVERRIDES}
            | {f for f, _ in _ENV_LITERAL_OVERRIDES}
        )
        config_fields = set(HydraFlowConfig.model_fields.keys())
        invalid = all_fields - config_fields
        assert not invalid, f"Invalid field names in override tables: {invalid}"
        # Every field in _ENV_LITERAL_OVERRIDES must actually have a Literal annotation
        # so that get_args() returns allowed values instead of an empty tuple.
        for field, _ in _ENV_LITERAL_OVERRIDES:
            field_info = HydraFlowConfig.model_fields[field]
            args = get_args(field_info.annotation)
            assert args, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no Literal args "
                f"(annotation={field_info.annotation!r}); "
                "all env var overrides for this field would be silently rejected"
            )
            # Every field must have at least one non-default allowed value so that
            # next(v for v in allowed if v != default) in the parametrized tests
            # never raises StopIteration.
            default = field_info.default
            non_defaults = [v for v in args if v != default]
            assert non_defaults, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no non-default Literal "
                f"value (default={default!r}, allowed={args}); "
                "test_env_literal_override_applies_when_at_default would raise StopIteration"
            )

    def test_override_table_defaults_match_field_defaults(self) -> None:
        """Default values in the override tables must match HydraFlowConfig field defaults.

        This prevents silent drift when a field default is changed without updating
        the corresponding entry in _ENV_INT_OVERRIDES or _ENV_STR_OVERRIDES.
        """
        model_fields = HydraFlowConfig.model_fields

        # Act / Assert — int overrides
        for field, _env_key, table_default in _ENV_INT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_INT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — str overrides
        for field, _env_key, table_default in _ENV_STR_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert str(pydantic_default) == table_default, (
                f"_ENV_STR_OVERRIDES entry for '{field}' has default={table_default!r}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default!r}"
            )

        # Act / Assert — float overrides
        for field, _env_key, table_default in _ENV_FLOAT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_FLOAT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — bool overrides
        for field, _env_key, table_default in _ENV_BOOL_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_BOOL_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )


def test_auto_tighten_loop_enabled_defaults_true_and_env_can_disable(monkeypatch):
    from config import HydraFlowConfig

    assert HydraFlowConfig().auto_tighten_loop_enabled is True
    monkeypatch.setenv("HYDRAFLOW_AUTO_TIGHTEN_LOOP_ENABLED", "false")
    assert HydraFlowConfig().auto_tighten_loop_enabled is False


class TestHumanSteeringAuthorizedUsersEnvOverride:
    """HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS (comma-separated list, special-case)."""

    def test_default_is_empty_list(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.human_steering_authorized_users == []

    def test_env_var_override_applies_when_at_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "steer-bot,octocat"
        )
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.human_steering_authorized_users == ["steer-bot", "octocat"]

    def test_env_var_override_strips_whitespace_and_drops_empties(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", " steer-bot , , octocat "
        )
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.human_steering_authorized_users == ["steer-bot", "octocat"]

    def test_explicit_value_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "steer-bot")
        cfg = HydraFlowConfig(
            human_steering_authorized_users=["custom-user"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.human_steering_authorized_users == ["custom-user"]

    def test_env_var_all_whitespace_leaves_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "  ,  ")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.human_steering_authorized_users == []


class TestDotenvLoading:
    """Verify python-dotenv is called at server startup."""

    def test_server_main_invokes_load_dotenv(self) -> None:
        """server.main() should call load_dotenv before config resolution."""
        import sys
        import types
        from unittest.mock import MagicMock, patch

        mock_config = MagicMock()
        mock_config.dashboard_enabled = False

        # The dotenv package may not be installed in the test environment.
        # Ensure a mock module is available so the local import inside main() succeeds.
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = MagicMock()  # type: ignore[attr-defined]

        with (
            patch.dict(sys.modules, {"dotenv": fake_dotenv}),
            patch("server.load_runtime_config", return_value=mock_config),
            patch("server.asyncio.run"),
            patch("server.setup_logging"),
            patch.dict("os.environ", {}, clear=False),
        ):
            from server import main

            # Explicit argv: main() parses the console-script CLI (#11580) and
            # would otherwise read pytest's own sys.argv (SystemExit 2 on CI).
            main([])
            fake_dotenv.load_dotenv.assert_called_once()


class TestEnvOptIntOverrideTable:
    """Optional-int overrides (CH-1, #9729): audit-stream retention floors."""

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_OPT_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_OPT_INT_OVERRIDES],
    )
    def test_env_opt_int_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int | None,
    ) -> None:
        monkeypatch.setenv(env_key, "2555")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == 2555

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_OPT_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_OPT_INT_OVERRIDES],
    )
    def test_env_opt_int_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int | None,
    ) -> None:
        monkeypatch.setenv(env_key, "365")
        cfg = HydraFlowConfig(
            **{field: 30},  # type: ignore[arg-type]
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == 30

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_OPT_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_OPT_INT_OVERRIDES],
    )
    @pytest.mark.parametrize("bad_value", ["not-a-number", "", "0", "-7"])
    def test_env_opt_int_override_invalid_or_out_of_range_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int | None,
        bad_value: str,
    ) -> None:
        monkeypatch.setenv(env_key, bad_value)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == default

    def test_opt_int_table_defaults_match_field_defaults(self) -> None:
        model_fields = HydraFlowConfig.model_fields
        for field, _env_key, table_default in _ENV_OPT_INT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_OPT_INT_OVERRIDES entry for '{field}' has "
                f"default={table_default}, but HydraFlowConfig.{field} "
                f"default is {pydantic_default}"
            )


class TestEnvVarEnumOverride:
    """StrEnum-typed env overrides (#10037: queue_strategy)."""

    @pytest.mark.parametrize(
        ("field", "env_key", "enum_cls"),
        _ENV_ENUM_OVERRIDES,
        ids=[entry[0] for entry in _ENV_ENUM_OVERRIDES],
    )
    def test_enum_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        enum_cls: type[QueueStrategy],
    ) -> None:
        # Pick a member other than the field default so the override is visible.
        default = HydraFlowConfig.model_fields[field].default
        target = next(member for member in enum_cls if member != default)
        monkeypatch.setenv(env_key, target.value)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == target

    def test_queue_strategy_override_lands_as_the_enum_member(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_QUEUE_STRATEGY", "weighted_mix")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.queue_strategy is QueueStrategy.WEIGHTED_MIX

    def test_invalid_queue_strategy_value_is_ignored_and_default_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_QUEUE_STRATEGY", "round_robin")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.queue_strategy is QueueStrategy.WEIGHTED_MIX


class TestEnvOverrideKeys:
    """#10859: env_override_keys() — superset of declared_env_keys() that also
    covers the inline os.environ reads outside the _ENV_*_OVERRIDES tables
    (repo/git-identity resolution, docker/profile knobs, JSON-shaped
    overrides). declared_env_keys() alone is not enough to build a hermetic
    config — it only covers the data-driven tables."""

    def test_returns_a_frozenset(self) -> None:
        assert isinstance(env_override_keys(), frozenset)

    def test_is_superset_of_declared_env_keys(self) -> None:
        assert declared_env_keys() <= env_override_keys()

    @pytest.mark.parametrize(
        "env_key",
        [
            "HYDRAFLOW_GITHUB_REPO",
            "HYDRAFLOW_GIT_USER_NAME",
            "HYDRAFLOW_GIT_USER_EMAIL",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            "HYDRAFLOW_DATA_ROOT",
            "HYDRAFLOW_HOME",
            "HYDRAFLOW_DOCKER_ENABLED",
            "HYDRA_DOCKER_ENABLED",
            "HYDRAFLOW_LITE_PLAN_LABELS",
            "HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS",
            "HYDRAFLOW_WORKTREE_GC_ROOTS",
            "HYDRAFLOW_DOCKER_MEMORY_LIMIT",
            "HYDRAFLOW_DOCKER_TMP_SIZE",
            "HYDRAFLOW_DOCKER_PIDS_LIMIT",
            "HYDRAFLOW_MANAGED_REPOS",
        ],
    )
    def test_contains_inline_non_table_keys(self, env_key: str) -> None:
        """The exact keys _resolve_base_paths / _resolve_repo_and_identity /
        _apply_env_overrides' special-case section read directly via
        os.environ or _get_env, outside any _ENV_*_OVERRIDES table."""
        assert env_key in env_override_keys()


class TestDeclaredDefaultConfig:
    """#10859: declared_default_config() builds a HydraFlowConfig reflecting
    only declared field defaults, independent of the host process's
    environment and repo_root/.env — ADR-0087's "same input -> same score"
    applied to the config the prompt audit renders from."""

    def test_ignores_table_driven_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "999")
        cfg = declared_default_config()
        assert (
            cfg.min_review_findings
            == HydraFlowConfig.model_fields["min_review_findings"].default
        )

    def test_ignores_inline_list_typed_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "leaked-user")
        cfg = declared_default_config()
        assert cfg.human_steering_authorized_users == []

    def test_ignores_non_prefixed_table_driven_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOG_INGEST_INTERVAL", "99999")
        cfg = declared_default_config()
        assert (
            cfg.log_ingest_interval
            == HydraFlowConfig.model_fields["log_ingest_interval"].default
        )

    def test_ignores_git_identity_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GIT_USER_NAME", "Leaked Name")
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Also Leaked")
        cfg = declared_default_config()
        assert cfg.git_user_name == ""

    def test_scrubs_a_git_prefixed_key_not_individually_listed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Belt-and-braces: tests/architecture/test_config_env_key_coverage.py
        treats any GIT_-prefixed literal as a safe prefix, not requiring an
        explicit env_override_keys() entry. That's only sound if
        declared_default_config() actually scrubs the whole GIT_ prefix —
        not just the four keys currently hand-listed — so a future GIT_-
        prefixed env read added anywhere in resolve_defaults's call graph
        can't pass that architecture ratchet while still leaking through
        here."""
        import config as config_module

        monkeypatch.setenv("GIT_SOME_FUTURE_KEY", "leaked")
        seen: dict[str, bool] = {}
        original = config_module._resolve_base_paths

        def _spy(cfg: HydraFlowConfig) -> None:
            seen["present"] = "GIT_SOME_FUTURE_KEY" in os.environ
            original(cfg)

        monkeypatch.setattr(config_module, "_resolve_base_paths", _spy)
        declared_default_config()
        assert seen["present"] is False

    def test_ignores_json_shaped_managed_repos_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MANAGED_REPOS is read via _get_env(...) with a literal
        key — the one spot outside the _ENV_*_OVERRIDES tables that reads a
        JSON-shaped value into a list field, easy to miss when enumerating
        env_override_keys()."""
        monkeypatch.setenv("HYDRAFLOW_MANAGED_REPOS", '[{"slug": "leaked/repo"}]')
        cfg = declared_default_config()
        assert cfg.managed_repos == []

    def test_ignores_dotenv_file_at_the_auto_detected_repo_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The one channel os.environ-scrubbing alone cannot close:
        ``_dotenv_lookup`` reads ``repo_root/.env`` directly for git
        identity, bypassing ``os.environ`` entirely. Regression coverage for
        a caller that doesn't pass an explicit ``repo_root`` — with no
        override, ``declared_default_config()`` must default to a fresh temp
        dir rather than let a real ``.env`` next to ``cwd`` leak in."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("HYDRAFLOW_GIT_USER_NAME=leaked-from-dotenv\n")
        cfg = declared_default_config()
        assert cfg.git_user_name == ""

    def test_explicit_repo_root_override_still_wins(self, tmp_path: Path) -> None:
        """Explicit field overrides take precedence, same as every other
        HydraFlowConfig field (see the "ignored_when_explicit_value_set"
        tests above)."""
        cfg = declared_default_config(repo_root=tmp_path)
        assert cfg.repo_root == tmp_path.resolve()

    def test_os_environ_restored_after_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "999")
        before = dict(os.environ)
        declared_default_config()
        assert dict(os.environ) == before

    def test_os_environ_restored_even_if_construction_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "999")
        before = dict(os.environ)
        with pytest.raises(ValidationError):
            declared_default_config(batch_size=99999)
        assert dict(os.environ) == before

    def test_rendered_corpus_fields_identical_with_and_without_env_overrides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The issue's acceptance criterion, applied directly to
        declared_default_config(): the set of fields the prompt audit
        captures (int/bool/str/float/list/dict, mirroring
        scripts/audit_prompts.py's _real_config_defaults() filter) must be
        byte-identical with and without a representative HYDRAFLOW_*
        override set spanning every suppression channel."""

        def _captured(cfg: HydraFlowConfig) -> dict[str, object]:
            return {
                name: getattr(cfg, name)
                for name in type(cfg).model_fields
                if isinstance(
                    getattr(cfg, name), int | bool | str | float | list | dict
                )
            }

        baseline = _captured(declared_default_config())

        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "999")
        monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "leaked")
        monkeypatch.setenv("LOG_INGEST_INTERVAL", "99999")
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Leaked Name")
        monkeypatch.setenv("HYDRAFLOW_WORKTREE_GC_ROOTS", "/leaked/root")
        overridden = _captured(declared_default_config())

        assert overridden == baseline


class TestDeclaredEnvKeys:
    """#10876: declared_env_keys() — public, runtime-derived accessor covering
    every env key any ``_ENV_*_OVERRIDES`` table reads, so conftest's test-
    isolation sweep never needs a hand-maintained list."""

    @pytest.mark.parametrize(
        "table",
        [
            _ENV_INT_OVERRIDES,
            _ENV_STR_OVERRIDES,
            _ENV_FLOAT_OVERRIDES,
            _ENV_OPT_FLOAT_OVERRIDES,
            _ENV_OPT_INT_OVERRIDES,
            _ENV_FLOAT_RATIO_OVERRIDES,
            _ENV_BOOL_OVERRIDES,
        ],
        ids=[
            "int",
            "str",
            "float",
            "opt_float",
            "opt_int",
            "float_ratio",
            "bool",
        ],
    )
    def test_contains_every_env_key_in_three_tuple_tables(self, table) -> None:
        declared = declared_env_keys()
        for _field, env_key, _default in table:
            assert env_key in declared

    def test_contains_every_env_key_in_literal_overrides(self) -> None:
        declared = declared_env_keys()
        for _field, env_key in _ENV_LITERAL_OVERRIDES:
            assert env_key in declared

    def test_contains_every_env_key_in_enum_overrides(self) -> None:
        declared = declared_env_keys()
        for _field, env_key, _enum_cls in _ENV_ENUM_OVERRIDES:
            assert env_key in declared

    def test_contains_every_env_key_in_combo_overrides(self) -> None:
        declared = declared_env_keys()
        for env_key, _tool_field, _model_field in _ENV_COMBO_OVERRIDES:
            assert env_key in declared

    def test_contains_deprecated_aliases_and_their_canonical_names(self) -> None:
        declared = declared_env_keys()
        for old_key, canonical_key in _DEPRECATED_ENV_ALIASES.items():
            assert old_key in declared
            assert canonical_key in declared

    @pytest.mark.parametrize(
        "env_key",
        ["LOG_INGEST_INTERVAL", "LOG_INGEST_WARNING_MIN_COUNT"],
    )
    def test_contains_known_non_prefixed_keys(self, env_key: str) -> None:
        """Non-prefixed, third-party-style env override keys must be declared."""
        assert env_key in declared_env_keys()

    def test_returns_a_frozenset(self) -> None:
        assert isinstance(declared_env_keys(), frozenset)

    def test_result_is_immutable(self) -> None:
        declared = declared_env_keys()
        with pytest.raises(AttributeError):
            declared.add("SOME_NEW_KEY")  # frozenset has no .add
