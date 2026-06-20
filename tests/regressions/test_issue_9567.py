"""Regression guards for issue #9567.

Two invariants that must not drift:

1. The env-var name documented in the slash-command skill file must match the
   name registered in ``_ENV_INT_OVERRIDES`` inside ``src/config.py``.
   Drift here means operators set an env var that is silently ignored.

2. The interactive slash-command file (``.claude/commands/hf.test-adequacy.md``)
   must remain a read-only assessment.  The deterministic coverage-delta check
   runs only inside the implementer loop; it must not be introduced as a
   behaviour of the slash command.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


# ---------------------------------------------------------------------------
# 1. Env-var name consistency
# ---------------------------------------------------------------------------


def test_coverage_timeout_env_var_registered_in_config() -> None:
    """The coverage timeout env var must appear in _ENV_INT_OVERRIDES."""
    import config as config_module

    env_var = "HYDRAFLOW_TEST_ADEQUACY_COVERAGE_TIMEOUT_SECS"
    registered = [entry[1] for entry in config_module._ENV_INT_OVERRIDES]
    assert env_var in registered, (
        f"{env_var!r} is not registered in config._ENV_INT_OVERRIDES; "
        "the env override would be silently ignored by operators"
    )


def test_coverage_timeout_field_default_matches_override_default() -> None:
    """The Field default and _ENV_INT_OVERRIDES tuple default must agree."""
    import config as config_module
    from config import HydraFlowConfig

    field_name = "test_adequacy_coverage_timeout_secs"
    field_default = HydraFlowConfig.model_fields[field_name].default

    tuple_default = next(
        entry[2] for entry in config_module._ENV_INT_OVERRIDES if entry[0] == field_name
    )

    assert field_default == tuple_default, (
        f"HydraFlowConfig.{field_name} Field default ({field_default}) "
        f"does not match _ENV_INT_OVERRIDES tuple default ({tuple_default}); "
        "the env override silently stops applying when they diverge"
    )


# ---------------------------------------------------------------------------
# 2. Slash-command read-only invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill_file",
    [
        REPO_ROOT / ".claude" / "commands" / "hf.test-adequacy.md",
        REPO_ROOT / ".codex" / "skills" / "hf.test-adequacy" / "SKILL.md",
    ],
)
def test_slash_command_remains_read_only(skill_file: Path) -> None:
    """The interactive skill files must still declare read-only behaviour.

    The deterministic coverage-delta cross-check runs only in the implementer
    loop (``AgentRunner._run_skill``).  It must NOT be mentioned as an action
    the slash-command performs, because the slash command has no worktree or
    subprocess access in interactive sessions.
    """
    if not skill_file.exists():
        pytest.skip(f"{skill_file} does not exist")

    text = skill_file.read_text()
    assert "read-only" in text.lower(), (
        f"{skill_file.name} no longer declares read-only behaviour; "
        "the slash command must remain a passive LLM assessment only"
    )
