"""Regression: apply_repo_config_overlay coerces nested-model fields.

The overlay assigned config-file values via ``object.__setattr__``, bypassing
Pydantic coercion — so ``managed_repos`` (``list[ManagedRepo]``) stayed a list
of raw dicts. That broke attribute access (``mr.enabled`` in
``PrinciplesAuditLoop`` -> ``AttributeError``) and emitted
``PydanticSerializationUnexpectedValue`` warnings on ``config.model_dump()``.
Reproduces against the production-shaped 'T-rav/poop-scoop' managed slug.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from config import HydraFlowConfig, ManagedRepo
from runtime_config import apply_repo_config_overlay, load_runtime_config


def test_overlay_coerces_managed_repos_dicts_to_models(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"managed_repos": [{"slug": "T-rav/poop-scoop", "enabled": True}]})
    )
    config = HydraFlowConfig(config_file=cfg_path)

    apply_repo_config_overlay(config)

    assert config.managed_repos
    assert all(isinstance(mr, ManagedRepo) for mr in config.managed_repos)
    assert config.managed_repos[0].slug == "T-rav/poop-scoop"
    # Attribute access that raised AttributeError on raw dicts in audit loops.
    assert config.managed_repos[0].enabled is True


def test_overlay_managed_repos_serialize_without_warning(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"managed_repos": [{"slug": "acme/widget", "enabled": False}]})
    )
    config = load_runtime_config(config_file=cfg_path)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = config.model_dump(mode="json")

    offenders = [
        str(w.message)
        for w in caught
        if "ManagedRepo" in str(w.message) or "managed_repos" in str(w.message)
    ]
    assert not offenders, offenders
    assert dumped["managed_repos"][0]["slug"] == "acme/widget"
    assert config.managed_repos[0].enabled is False
