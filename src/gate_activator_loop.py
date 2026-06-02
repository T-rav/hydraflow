"""Caretaker loop: propose activating planned gates whose surface now exists.

The growth half of ADR-0082. Where ``BranchProtectionAuditorLoop`` checks that
live GitHub protection matches the contract, this loop watches the contract
itself: it finds gates marked ``status = "planned"`` whose protected surface has
materialised (the producing CI job and make target now exist, and the gate binds
to the repo profile) and files one deduped issue proposing they be activated.

The proposal is a reviewed issue carrying the exact edit and the regenerate
command, never a direct GitHub ruleset mutation — the human's follow-up commit
is the audit trail. Follows ADR-0029 (caretaker pattern) and ADR-0049
(kill-switch convention).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from scripts.gates.activation import ActivationProposal

    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.gate_activator")

_ACTIVATION_LABELS = ["hydraflow-find", "hydraflow-gate-activation"]


def _proposal_key(repo: str, proposals: list[ActivationProposal]) -> str:
    """Stable dedup key: same set of activatable gates => no re-file.

    Namespaced by ``repo`` (parity with the auditor's ``_drift_key``) so a
    dedup store can never cross-contaminate between repos.
    """
    names = "\n".join(sorted(p.name for p in proposals))
    digest = hashlib.sha256(names.encode()).hexdigest()
    return f"gate_activator:{repo}:{digest[:16]}"


def _issue_title(proposals: list[ActivationProposal]) -> str:
    n = len(proposals)
    plural = "gate" if n == 1 else "gates"
    return f"[gate-activation] {n} planned {plural} ready to activate"


def _issue_body(proposals: list[ActivationProposal]) -> str:
    rows = "\n".join(
        f"- `{p.name}` (dimension `{p.dimension}`, required on "
        f"{', '.join(p.required_on) or '(none)'}): producer "
        f"`{p.workflow}:{p.job}`"
        + (f", make target `{p.make_target}`" if p.make_target else "")
        for p in proposals
    )
    return (
        "## Planned gates ready to activate\n\n"
        "These gates in `docs/standards/branch_protection/gates.toml` are marked "
        '`status = "planned"`, but the surface each protects now exists — its '
        "producing CI job and make target are present, and it binds to this "
        "repo's profile. Per ADR-0082 they should be activated so the guardrail "
        "is enforced.\n\n"
        f"{rows}\n\n"
        'To activate, set `status = "active"` on each gate above in '
        "`gates.toml`, then regenerate the artifacts and re-apply protection:\n\n"
        "```bash\n"
        "make gen-gates\n"
        "python scripts/setup_branch_protection.py --apply\n"
        "```\n\n"
        "Recording the decision as a reviewed change keeps git history the "
        "audit trail (no direct ruleset mutation). Filed by the `gate_activator` "
        "caretaker loop (ADR-0082, ADR-0029)."
    )


class GateActivatorLoop(BaseBackgroundLoop):
    """Files an issue proposing activation of planned-but-now-enforceable gates.

    Caretaker loop for ADR-0082 (declarative gate contract); follows ADR-0029
    (caretaker pattern) and ADR-0049 (kill-switch convention).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        dedup: DedupStore,
        deps: LoopDeps,
        *,
        detector: Callable[[], Awaitable[list[ActivationProposal]]],
    ) -> None:
        super().__init__(worker_name="gate_activator", config=config, deps=deps)
        self._prs = pr_manager
        self._dedup = dedup
        self._detector = detector

    def _get_default_interval(self) -> int:
        return self._config.gate_activator_interval

    async def _do_work(self) -> dict[str, Any] | None:  # noqa: PLR0911
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.gate_activator_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        try:
            proposals = await self._detector()
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("gate-activation detection failed", exc_info=True)
            return {"error": True}

        if not proposals:
            return {"status": "clean"}

        key = _proposal_key(self._config.repo, proposals)
        if key in self._dedup.get():
            return {"status": "proposals", "deduped": True}

        try:
            issue = await self._prs.create_issue(
                _issue_title(proposals),
                _issue_body(proposals),
                labels=_ACTIVATION_LABELS,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("could not file gate-activation issue", exc_info=True)
            return {"status": "proposals", "error": True}

        if issue == 0:
            logger.error(
                "gate activator: create_issue returned 0 (sentinel) — not "
                "tracking phantom issue; will retry next cycle"
            )
            return {"status": "proposals", "error": True}

        self._dedup.add(key)
        logger.info(
            "gate activator: filed issue #%d proposing %d gate activation(s)",
            issue,
            len(proposals),
        )
        return {"status": "proposals", "issue_created": issue}
