"""sandbox_main bootstrap with empty seed — proves wiring resolves."""

from __future__ import annotations

import os
from unittest.mock import patch

from mockworld import sandbox_main
from mockworld.sandbox_main import _build_caretaker_enabled_cb


def test_load_seed_returns_empty_when_no_path() -> None:
    with (
        patch.object(sandbox_main.sys, "argv", ["sandbox_main"]),
        patch.dict(os.environ, {}, clear=False),
    ):
        # Clear the env var if set
        os.environ.pop("HYDRAFLOW_MOCKWORLD_SEED", None)
        seed = sandbox_main._load_seed()
    assert seed.issues == []
    assert seed.prs == []


def test_load_seed_reads_file_path_from_argv(tmp_path) -> None:
    seed_path = tmp_path / "scenario.json"
    seed_path.write_text(
        '{"repos": [], "issues": [{"number": 1, "title": "t", "body": "b", "labels": []}],'
        ' "prs": [], "scripts": {}, "cycles_to_run": 4, "loops_enabled": null}'
    )
    with patch.object(sandbox_main.sys, "argv", ["sandbox_main", str(seed_path)]):
        seed = sandbox_main._load_seed()
    assert len(seed.issues) == 1
    assert seed.issues[0]["number"] == 1


def test_caretaker_enabled_cb_none_enables_all() -> None:
    """``loops_enabled=None`` (default) → every caretaker enabled."""
    cb = _build_caretaker_enabled_cb(None)
    assert cb("workspace_gc") is True
    assert cb("dependabot_merge") is True
    assert cb("anything_else") is True


def test_caretaker_enabled_cb_empty_disables_all() -> None:
    """``loops_enabled=[]`` → universal kill-switch (ADR-0049, #8483).

    Every caretaker name returns False so their in-body
    ``self._enabled_cb(self._worker_name)`` gate trips and no ``_do_work``
    runs. Phase orchestrators are not gated by this callback (they use
    ``BGWorkerManager.is_enabled`` via the orchestrator), so they remain
    unaffected — that's the per-#8483-triage-comment contract.
    """
    cb = _build_caretaker_enabled_cb([])
    assert cb("workspace_gc") is False
    assert cb("dependabot_merge") is False
    assert cb("ci_monitor") is False


def test_caretaker_enabled_cb_subset_enables_only_named() -> None:
    """``loops_enabled=["x","y"]`` → only x and y caretakers enabled."""
    cb = _build_caretaker_enabled_cb(["dependabot_merge", "workspace_gc"])
    assert cb("dependabot_merge") is True
    assert cb("workspace_gc") is True
    assert cb("ci_monitor") is False
    assert cb("sentry_ingest") is False


def test_caretaker_enabled_cb_tolerates_extra_args() -> None:
    """The callback is invoked from ``LoopDeps.enabled_cb`` which historically
    took ``(name)`` but some call sites pass extra positional/keyword args.
    Match the prior ``lambda *_a, **_kw: True`` tolerance.
    """
    cb_all = _build_caretaker_enabled_cb(None)
    cb_subset = _build_caretaker_enabled_cb(["workspace_gc"])
    # Should not raise.
    assert cb_all("workspace_gc", "extra", key="val") is True
    assert cb_subset("workspace_gc", "extra", key="val") is True
    assert cb_subset("other", "extra", key="val") is False
