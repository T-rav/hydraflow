"""Repo-wide harness backend override — spawn routing (#11211).

Each registered repo owns an independent ``HydraFlowConfig`` (one per
``RepoRuntime``, see ``repo_store.py``/``repo_runtime.py``), so a repo's
``repo_provider``/``repo_model`` dial is already inherently per-repo — no new
global or per-repo state to manage here, unlike ``credit_failover``'s
process-wide singleton.

:func:`apply_repo_provider` mirrors ``credit_failover.apply_credit_failover``'s
contract exactly and is applied at the SAME two spawn seams, immediately
BEFORE it: ``base_runner._execute`` and ``BaseSubprocessRunner.run``. The
combined resolution order at each seam is:

    role dial (an explicit non-claude ``*_provider``) > repo_provider > credit-failover

A role dial that has already routed a spawn off ``"claude"`` always wins (this
function only acts when the provider it's handed is still ``"claude"``).
Credit-failover is layered on top of whatever this function resolves: once a
repo's spawn is on ``"zai"`` (whether via a role dial or ``repo_provider``),
``apply_credit_failover``'s own ``provider != "claude"`` guard is a no-op — a
GLM-native repo is untouched by a Claude-cap failover engaged for a different,
Claude-native repo sharing the same process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config import LANE_DEFAULT_MODEL_FIELD
from credit_failover import kimi_key_present, zai_key_present
from prompt_telemetry import parse_command_tool_model, rewrite_command_model

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from config import HydraFlowConfig


#: Direct harness lane a repo can be pinned to -> "is its key present here?".
#: Membership is what makes the dial act at all: a lane absent from this map is
#: a `repo_provider` value the operator can select and save, that renders in the
#: UI, and that reroutes nothing. That is what `kimi` was between gaining a dial
#: and gaining this row — configured, displayed, and inert.
DIRECT_HARNESS_KEY_PRESENT: Mapping[str, Callable[[], bool]] = {
    "zai": zai_key_present,
    "kimi": kimi_key_present,
}


def _default_model_for(repo_provider: str, config: HydraFlowConfig) -> str:
    """The model a repo override rewrites to when `repo_model` is unset.

    Returns "" for a lane with nothing to inherit. The caller must not rewrite
    on an empty model: `rewrite_command_model(cmd, "")` does not decline, it
    sets `--model ""` on the spawned CLI, which fails as an opaque upstream
    error rather than as the missing configuration it is.
    """
    field = LANE_DEFAULT_MODEL_FIELD.get(repo_provider)
    return str(getattr(config, field, "")) if field else ""


def apply_repo_provider(
    provider: str, cmd: list[str], config: HydraFlowConfig
) -> tuple[str, list[str]]:
    """Reroute a still-Claude spawn to this repo's zai override, rewriting ``--model``.

    Returns ``(provider, cmd)`` unchanged unless ALL hold: *provider* is still
    ``"claude"`` (no role dial has already routed it elsewhere), the repo's
    ``repo_provider == "zai"``, and a ``ZAI_API_KEY`` is present (mirroring
    ``apply_credit_failover``'s fail-safe: never reroute to an endpoint with no
    key — that would send a glm-* model to the wrong backend). The rewritten
    model is ``config.repo_model`` when set, else ``config.credit_failover_model``.
    The input *cmd* is never mutated.
    """
    if provider != "claude":
        return provider, cmd
    repo_provider = config.repo_provider
    if repo_provider not in {"gateway", *DIRECT_HARNESS_KEY_PRESENT}:
        return provider, cmd
    tool, _ = parse_command_tool_model(cmd)
    if tool == "codex":
        return provider, cmd
    if repo_provider == "gateway":
        model = config.repo_model.strip()
        return (
            "gateway",
            rewrite_command_model(cmd, model) if model else cmd,
        )
    model = config.repo_model.strip() or _default_model_for(repo_provider, config)
    # No key, or no model to ask for: leave the spawn alone. The second half is
    # the guard the gateway branch above already had — load-time validation
    # should have refused a lane that can resolve no model, so reaching here
    # means something bypassed it, and rerouting while asking for `--model ""`
    # is worse than not rerouting.
    if not DIRECT_HARNESS_KEY_PRESENT[repo_provider]() or not model:
        return provider, cmd
    return repo_provider, rewrite_command_model(cmd, model)
