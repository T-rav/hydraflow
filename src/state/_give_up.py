"""Give-up window state — per-``(issue, child-class)`` restart-intensity (#10735).

Implements :class:`~giveup_window.GiveUpStore` against the JSON-backed
``StateTracker`` so the ``N``-in-``T`` give-up window survives restart. Without
persistence, a crash mid-thrash would reset the window and let a non-convergent
issue oscillate indefinitely — exactly the #10731 failure this closes.

Keyed by ``str(issue_id)`` (via ``self._key``) so the field is a normal
issue-scoped dict: ``StateGCMixin`` prunes a closed issue's give-up state along
with its other per-issue counters (``give_up_events`` is listed in
``_gc._ISSUE_SCOPED_FIELDS``). The per-child-class breakdown lives nested inside
each issue's value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from models import GiveUpClassState, GiveUpIssueState

if TYPE_CHECKING:
    from models import StateData


class GiveUpStateMixin:
    """Per-``(issue, class)`` give-up window accessors — satisfies GiveUpStore."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker; noqa: ARG004

    def _giveup_class(
        self, issue_id: int, child_class: str, *, create: bool
    ) -> GiveUpClassState | None:
        """Return the class-state for *issue_id*/*child_class*.

        When ``create`` is True a missing issue/class record is materialised
        (and the caller must ``save``); when False, missing returns ``None``.
        """
        key = self._key(issue_id)
        issue_state = self._data.give_up_events.get(key)
        if issue_state is None:
            if not create:
                return None
            issue_state = GiveUpIssueState()
            self._data.give_up_events[key] = issue_state
        cls_state = issue_state.classes.get(child_class)
        if cls_state is None:
            if not create:
                return None
            cls_state = GiveUpClassState()
            issue_state.classes[child_class] = cls_state
        return cls_state

    def record_give_up_event(
        self, issue_id: int, child_class: str, timestamp: float
    ) -> None:
        """Append a give-up event timestamp for *issue_id*/*child_class*."""
        cls_state = self._giveup_class(issue_id, child_class, create=True)
        assert cls_state is not None  # create=True always returns a state
        cls_state.timestamps.append(float(timestamp))
        self.save()

    def get_give_up_timestamps(self, issue_id: int, child_class: str) -> list[float]:
        """Return the recorded give-up timestamps (empty if none)."""
        cls_state = self._giveup_class(issue_id, child_class, create=False)
        return list(cls_state.timestamps) if cls_state else []

    def set_give_up_timestamps(
        self, issue_id: int, child_class: str, timestamps: list[float]
    ) -> None:
        """Replace the timestamp list (used by the tracker to prune the window)."""
        cls_state = self._giveup_class(issue_id, child_class, create=True)
        assert cls_state is not None
        cls_state.timestamps = [float(t) for t in timestamps]
        self.save()

    def record_give_up_action(
        self, issue_id: int, child_class: str, action: str, timestamp: float
    ) -> None:
        """Record which self-solve action fired when the window was exhausted."""
        cls_state = self._giveup_class(issue_id, child_class, create=True)
        assert cls_state is not None
        cls_state.last_action = action
        cls_state.action_count += 1
        cls_state.last_exhausted_ts = float(timestamp)
        self.save()

    def get_give_up_class_state(
        self, issue_id: int, child_class: str
    ) -> GiveUpClassState | None:
        """Return a copy of the class-state, or ``None`` if untracked."""
        cls_state = self._giveup_class(issue_id, child_class, create=False)
        return cls_state.model_copy(deep=True) if cls_state else None

    def reset_give_up(self, issue_id: int, child_class: str) -> None:
        """Clear the give-up window for *issue_id*/*child_class* (on convergence).

        The timestamps are dropped so a converged issue starts fresh; the
        ``action_count``/``last_action`` audit fields are preserved so a later
        ``/api`` read still shows the historical self-solve, not a blank slate.
        """
        cls_state = self._giveup_class(issue_id, child_class, create=False)
        if cls_state is None or not cls_state.timestamps:
            return
        cls_state.timestamps = []
        self.save()

    def get_give_up_snapshot(self, issue_id: int) -> dict[str, Any]:
        """Return the full give-up state for *issue_id* (all classes), for /api."""
        issue_state = self._data.give_up_events.get(self._key(issue_id))
        if issue_state is None:
            return {}
        return {
            cls: {
                "cycle_count": len(state.timestamps),
                "last_action": state.last_action,
                "action_count": state.action_count,
                "last_exhausted_ts": state.last_exhausted_ts,
            }
            for cls, state in issue_state.classes.items()
        }

    def all_give_up_snapshots(self) -> dict[int, dict[str, Any]]:
        """Return give-up snapshots for every tracked issue, keyed by int id."""
        out: dict[int, dict[str, Any]] = {}
        for key in self._data.give_up_events:
            try:
                issue_id = int(key)
            except ValueError:
                continue
            snap = self.get_give_up_snapshot(issue_id)
            if snap:
                out[issue_id] = snap
        return out
