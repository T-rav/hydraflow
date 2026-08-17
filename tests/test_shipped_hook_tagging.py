"""Guard: every shipped hook carries the ``_hydraflow`` ownership tag (#11248).

``merge_assets.merge_settings_file`` merges ONLY ``_hydraflow``-tagged
entries into an existing user settings file — that tag is what makes an
entry identifiable as HydraFlow-owned on a later upgrade or uninstall.
The fresh-install path, by contrast, copies the shipped file wholesale.

So the two paths agree if and only if every shipped hook is tagged. They
did agree — by luck, not by construction (#11248: an untagged shipped
hook is silently dropped when merging into an existing repo, but present
in a fresh one; same source, different result). This guard makes the
invariant enforced rather than lucky. The alternative fix — merging
untagged entries too — was ruled out: it orphans entries HydraFlow can
never identify as its own.
"""

from __future__ import annotations

import json
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SETTINGS = _REPO / ".claude" / "settings.json"


def _shipped_hooks() -> list[tuple[str, str, dict]]:
    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    out: list[tuple[str, str, dict]] = []
    for event, entries in (data.get("hooks") or {}).items():
        for entry in entries:
            matcher = entry.get("matcher", "*")
            for hook in entry.get("hooks", []):
                out.append((event, matcher, hook))
    return out


def test_settings_file_ships_hooks() -> None:
    """Anti-vacuity: the guard must be scanning a real, populated file."""
    assert _SETTINGS.exists()
    assert len(_shipped_hooks()) >= 10


def test_shipped_hooks_are_hydraflow_tagged() -> None:
    untagged = [
        f"{event}:{matcher}:{(hook.get('command') or '')[:60]}"
        for event, matcher, hook in _shipped_hooks()
        if not hook.get("_hydraflow")
    ]
    assert not untagged, (
        "Shipped hook(s) missing the `_hydraflow` ownership tag: "
        f"{untagged}. merge_settings_file merges ONLY tagged entries, so an "
        "untagged hook is silently dropped when installing into an existing "
        "repo while appearing in a fresh one (#11248). Tag it — do not widen "
        "the merge, which would orphan entries HydraFlow cannot identify."
    )


def test_install_paths_agree_on_the_shipped_set() -> None:
    """The symmetry the tag invariant buys: what a merge install applies
    equals what a fresh install copies."""
    from scripts.merge_assets import _is_hf_entry

    data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    for entries in (data.get("hooks") or {}).values():
        for entry in entries:
            assert _is_hf_entry(entry), (
                f"matcher {entry.get('matcher')!r} would be skipped by a "
                "merge install but copied by a fresh install (#11248)."
            )
