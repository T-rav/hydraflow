"""Tests for dx/hydraflow/config.py — Env var overrides."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import get_args

import pytest

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
    HydraFlowConfig,
    declared_env_keys,
)
from queue_strategy import QueueStrategy

# ---------------------------------------------------------------------------
# Data-driven env-var override table validation
# ---------------------------------------------------------------------------


class TestEnvVarOverrideTable:
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
        monkeypatch.setenv(env_key, "custom-value")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        result = getattr(cfg, field)
        assert str(result) == "custom-value"

    # Valid non-default explicit values for Literal-typed string fields.
    # Generic tests can't use arbitrary strings for these fields.
    _EXPLICIT_VALUES: dict[str, str] = {
        "execution_mode": "docker",
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
        monkeypatch.setenv(env_key, "env-value")
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
        """Bool overrides should treat '1', 'true', 'yes' as True."""
        for truthy in ("1", "true", "yes", "True", "YES"):
            monkeypatch.setenv(env_key, truthy)
            cfg = HydraFlowConfig(
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


class TestOtelConfigFields:
    def test_config_otel_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Hermetic: the repo .env sets HF_ENV=dev and HYDRAFLOW_OTEL_ENABLED=true.
        # Under pytest-xdist, a sibling test that loads .env into os.environ can
        # leak those into this worker and flip the asserted defaults (the
        # historical "assert 'dev' == 'local'" flake). Clear the backing env vars
        # so we assert the true compile-time defaults regardless of leakage.
        for _var in (
            "HYDRAFLOW_OTEL_ENABLED",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_SERVICE_NAME",
            "HF_ENV",
        ):
            monkeypatch.delenv(_var, raising=False)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.otel_enabled is False
        assert cfg.otel_endpoint == "https://api.honeycomb.io"
        assert cfg.otel_service_name == "hydraflow"
        assert cfg.otel_environment == "local"

    def test_config_otel_env_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_OTEL_ENABLED", "true")
        monkeypatch.setenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.eu1.honeycomb.io"
        )
        monkeypatch.setenv("OTEL_SERVICE_NAME", "hydraflow-test")
        monkeypatch.setenv("HF_ENV", "staging")

        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.otel_enabled is True
        assert cfg.otel_endpoint == "https://api.eu1.honeycomb.io"
        assert cfg.otel_service_name == "hydraflow-test"
        assert cfg.otel_environment == "staging"


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

            main()
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
        ["SENTRY_ORG", "HF_ENV", "OTEL_SERVICE_NAME", "LOG_INGEST_INTERVAL"],
    )
    def test_contains_known_non_prefixed_keys(self, env_key: str) -> None:
        """The exact keys the issue calls out — SENTRY_ORG and friends."""
        assert env_key in declared_env_keys()

    def test_returns_a_frozenset(self) -> None:
        assert isinstance(declared_env_keys(), frozenset)

    def test_result_is_immutable(self) -> None:
        declared = declared_env_keys()
        with pytest.raises(AttributeError):
            declared.add("SOME_NEW_KEY")  # frozenset has no .add
