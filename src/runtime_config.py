"""Runtime configuration loader for HydraFlow server."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import TypeAdapter, ValidationError

from config import HydraFlowConfig, load_config_file

logger = logging.getLogger("hydraflow.runtime_config")

# Repo-identity and data-governance keys the boot/register callers always own.
# They are layered on top of stored per-repo overrides, so a stale or
# hand-edited stored value can never hijack repo identity or the CH-6 data-class
# merge (#10658). Never replayed from ``RepoRecord.overrides``.
_STRUCTURAL_OVERRIDE_KEYS = frozenset({"repo_root", "repo", "repo_data_class"})


def _default_data_root_path() -> Path:
    """Return the preferred HydraFlow data root."""
    env_home = os.environ.get("HYDRAFLOW_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    return Path(".hydraflow")


DEFAULT_CONFIG_PATH = _default_data_root_path() / "config.json"
DEFAULT_LOG_FILE = _default_data_root_path() / "logs" / "hydraflow.log"


def _coerce_overlay_value(field_name: str, value: Any) -> Any:
    """Coerce a raw overlay value to its config field's declared type.

    The overlay assigns via ``object.__setattr__``, which bypasses Pydantic
    validation/coercion — so nested-model fields (notably
    ``managed_repos: list[ManagedRepo]``) would be left as raw dicts, breaking
    attribute access (``mr.enabled``) and emitting serializer warnings on
    ``model_dump()``. Validate through the field's annotation so the value
    matches the constructor path. Fall back to the raw value for any annotation
    that cannot be adapted (arbitrary types) so behavior never regresses.
    """
    annotation = HydraFlowConfig.model_fields[field_name].annotation
    try:
        return TypeAdapter(annotation).validate_python(value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("overlay: leaving %s un-coerced (%s)", field_name, exc)
        return value


def apply_repo_config_overlay(
    config: HydraFlowConfig, cli_explicit: set[str] | None = None
) -> None:
    """Apply repo-scoped config overlay, mirroring legacy CLI behavior."""
    explicit = cli_explicit or set()
    if config.config_file is None:
        return
    repo_cfg = load_config_file(config.config_file)
    if not repo_cfg:
        return
    known_fields = set(HydraFlowConfig.model_fields.keys())
    for key, val in repo_cfg.items():
        if key in known_fields and key not in explicit:
            object.__setattr__(config, key, _coerce_overlay_value(key, val))


def valid_stored_overrides(overrides: Mapping[str, Any], slug: str) -> dict[str, Any]:
    """Return the replayable subset of a repo's persisted ``overrides``.

    Operator edits from ``PATCH /api/control/config?repo=X`` are persisted into
    ``RepoRecord.overrides`` in ``repos.json`` (``repo_store.update_overrides``).
    The boot restore / repo-register seams read them back through this filter so
    an edit survives a restart (#10658). Each stored value is validated against
    its ``HydraFlowConfig`` field's declared type **and** range constraints:

    * Unknown keys and out-of-range / wrong-typed values are dropped with a
      warning naming ``slug`` — ``repos.json`` is hand-editable and the schema
      may narrow over time, so a single bad value degrades to that field's
      default instead of raising and dropping the whole repo.
    * Structural keys (``repo_root`` / ``repo`` / ``repo_data_class``) are never
      replayed; the caller layers those on top so a stored value can never
      hijack repo identity or the CH-6 data-class governance merge.

    The returned keys are handed to ``load_runtime_config(overrides=...)``, so
    they become *explicit* fields — matching #10657's precedence, they beat a
    conflicting ``HYDRAFLOW_*`` env var, while a field with no stored edit still
    lets the env var win.
    """
    model_fields = HydraFlowConfig.model_fields
    valid: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in _STRUCTURAL_OVERRIDE_KEYS:
            continue
        field_info = model_fields.get(key)
        if field_info is None:
            logger.warning("Ignoring unknown stored override %r for repo %s", key, slug)
            continue
        annotation = field_info.annotation
        metadata = field_info.metadata
        if metadata:
            annotation = Annotated[(annotation, *metadata)]
        try:
            TypeAdapter(annotation).validate_python(value)
        except ValidationError:
            logger.warning(
                "Ignoring invalid stored override %s=%r for repo %s; "
                "falling back to the default",
                key,
                value,
                slug,
            )
            continue
        valid[key] = value
    return valid


def load_runtime_config(
    config_file: str | os.PathLike[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> HydraFlowConfig:
    """Load HydraFlow configuration from disk, applying overrides."""
    env_override = os.environ.get("HYDRAFLOW_CONFIG_FILE", "").strip()
    chosen_path: Path
    if config_file is not None:
        chosen_path = Path(config_file).expanduser().resolve()
    elif env_override:
        chosen_path = Path(env_override).expanduser().resolve()
    else:
        chosen_path = DEFAULT_CONFIG_PATH.expanduser().resolve()

    file_kwargs = load_config_file(chosen_path)
    known_fields = set(HydraFlowConfig.model_fields.keys())
    kwargs: dict[str, Any] = {
        key: value for key, value in file_kwargs.items() if key in known_fields
    }
    kwargs["config_file"] = chosen_path

    explicit_fields: set[str] = set()
    if overrides:
        for key, value in overrides.items():
            if key in known_fields:
                kwargs[key] = value
                explicit_fields.add(key)

    config = HydraFlowConfig(**kwargs)
    apply_repo_config_overlay(config, explicit_fields)
    return config


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_LOG_FILE",
    "apply_repo_config_overlay",
    "load_runtime_config",
    "valid_stored_overrides",
]
