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

from credit_failover import zai_key_present
from prompt_telemetry import rewrite_command_model

if TYPE_CHECKING:
    from config import HydraFlowConfig


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
    if config.repo_provider != "zai":
        return provider, cmd
    if not zai_key_present():
        return provider, cmd
    model = config.repo_model.strip() or config.credit_failover_model
    return "zai", rewrite_command_model(cmd, model)
