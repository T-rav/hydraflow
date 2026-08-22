"""Single-owner registry for issues held by a live ``IssueDriver`` (#11535).

Under ``issue_controller`` scheduling an issue is owned end-to-end by one fenced
driver. Everything else in the factory that could *also* start driving that
issue must be able to see the claim and stand down — otherwise the controller
does not remove the duplicate-owner hazard, it adds one.

The concrete hazard #11535 names is **AutoAgent**. It has two intake paths that
each take an issue and run it to a PR in a single session:

* ``AutoAgentPreflightLoop`` intercepts idle ``hydraflow-hitl`` /
  ``hitl-escalation`` issues (``auto_agent_hitl_intake_enabled``);
* ``PlanPhase``'s light lane routes low-complexity issues to the same
  single-session agent (``auto_agent_light_intake_enabled``).

Both are correct under Classic, where nothing else owns the issue. Under the
controller both would be a **second owner** of an issue a driver already holds.
This registry is the interlock, and it answers the question the same way for
every caller so there is one definition of "owned".

**Default-off by construction.** The registry is constructed disabled under
Classic and :meth:`DriverOwnershipRegistry.owns` then returns ``False`` for
every issue without consulting any state at all — an operator who has not opted
in gets byte-identical AutoAgent behaviour, and that is provable by reading this
method rather than by auditing every call site. A disabled registry also refuses
to record a claim, so an ownership entry cannot be created on a Classic factory
by any path.

The registry is deliberately **process-local and not durable**. Ownership is not
a source of truth — GitHub labels are (ADR-0002). On boot there are no live
drivers, so there are no claims; ``DriverManager`` re-derives what to drive from
labels and re-claims as it admits. Persisting ownership would create exactly the
second source of truth ADR-0137 C1 forbids.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger("driver_ownership")


@dataclass(frozen=True)
class DriverClaim:
    """Who owns an issue right now.

    ``epoch`` is the fencing token from :class:`driver_contracts.DriverLease`:
    a recovered driver claims at a higher epoch, and a stale holder's release
    at the old epoch is refused rather than silently freeing the new owner's
    claim.
    """

    issue_number: int
    driver_id: str
    epoch: int


class DriverOwnershipRegistry:
    """Compare-and-set ownership of issues held by live drivers.

    Thread-safe because the callers do not share one event loop: the phase
    loops, the background loops and the dashboard all read it.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled
        self._claims: dict[int, DriverClaim] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """True only under a scheduling preset that runs per-issue drivers."""
        return self._enabled

    @property
    def owned_issues(self) -> frozenset[int]:
        """Issue numbers currently held by a driver. Always empty under Classic."""
        if not self._enabled:
            return frozenset()
        with self._lock:
            return frozenset(self._claims)

    def owns(self, issue_number: int) -> bool:
        """True when a live driver holds *issue_number*.

        The one predicate every "should I stand down?" guard calls. Returns
        ``False`` immediately when the registry is disabled, which is what makes
        the Classic path free of both a behaviour change and a lock acquisition.
        """
        if not self._enabled:
            return False
        with self._lock:
            return issue_number in self._claims

    def claim(self, issue_number: int, *, driver_id: str, epoch: int) -> bool:
        """Take ownership of *issue_number*; ``False`` when someone else holds it.

        Compare-and-set, not last-write-wins: a second driver for an
        already-claimed issue is refused, so "one fenced driver per issue" is
        enforced by the registry rather than trusted of the caller. A re-claim
        by the *same* driver at a **higher or equal** epoch succeeds — that is
        recovery re-taking its own issue at a new epoch, not a second owner.
        """
        if not self._enabled:
            logger.debug(
                "ownership claim for #%d ignored — registry disabled (Classic)",
                issue_number,
            )
            return False
        with self._lock:
            held = self._claims.get(issue_number)
            if held is not None and not (
                held.driver_id == driver_id and epoch >= held.epoch
            ):
                return False
            self._claims[issue_number] = DriverClaim(
                issue_number=issue_number, driver_id=driver_id, epoch=epoch
            )
            return True

    def release(self, issue_number: int, *, driver_id: str, epoch: int) -> bool:
        """Drop ownership; ``False`` when the caller is not the current holder.

        A stale driver that finishes after being fenced out by recovery must not
        free the new owner's claim, so the epoch is checked as well as the id.
        """
        if not self._enabled:
            return False
        with self._lock:
            held = self._claims.get(issue_number)
            if held is None:
                return False
            if held.driver_id != driver_id or held.epoch != epoch:
                logger.warning(
                    "refused stale ownership release for #%d by %s@%d "
                    "(current holder %s@%d)",
                    issue_number,
                    driver_id,
                    epoch,
                    held.driver_id,
                    held.epoch,
                )
                return False
            del self._claims[issue_number]
            return True

    def release_all(self) -> None:
        """Drop every claim. Called on factory stop so nothing survives a drain."""
        with self._lock:
            self._claims.clear()
