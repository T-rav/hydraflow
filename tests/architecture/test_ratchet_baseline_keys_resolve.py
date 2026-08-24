"""Ratchet baseline keys must name a file that still exists.

Refs #11673. Four shrink-only ratchets key their grandfather baselines by
source path: ``"src/<path>.py::<Class>.<method>"`` (or ``:<Class>`` for the
mass baseline). The scanners emit that same spelling, so the key IS a file
path, not a module identity.

The class failure: decomposing a module re-keys every entry it holds. The old
key stops matching, the scanner reports the site under its new path, and the
disappearance of the old entry is read by a SHRINK-ONLY ratchet as progress —
the one direction it is built to allow without complaint. A rename is filed as
a fix. Nothing reddens.

These assertions are the loud half. Today every key resolves, so they are green
on arrival and bite the moment one does not — which is exactly when a
decomposition has quietly re-keyed a baseline and nobody has re-pointed it.

Deliberately STRICT file existence, not ``path_membership.module_identities``:
an identity walk would accept ``src/foo/`` for a stale ``src/foo.py`` key and
call it resolved, when that key is precisely the dead weight this exists to
surface. Several entries already name package members
(``src/dashboard_routes/_routes.py``, ``src/preflight/__init__.py``), so a real
file is always the right bar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: ``(display name, module path, attribute)`` for each dict/set baseline.
_CODE_BASELINES: tuple[tuple[str, str, str], ...] = (
    (
        "GRANDFATHERED_UNDECLARED",
        "tests/architecture/test_restricted_mode_declaration.py",
        "GRANDFATHERED_UNDECLARED",
    ),
    (
        "GRANDFATHERED_RAW_SPAWN_BASELINE",
        "tests/architecture/test_subprocess_reap_guard.py",
        "GRANDFATHERED_RAW_SPAWN_BASELINE",
    ),
    (
        "GRANDFATHERED_SPAWN_BASELINE",
        "tests/architecture/test_sandbox_seam_completeness.py",
        "GRANDFATHERED_SPAWN_BASELINE",
    ),
)

_MASS_BASELINE = _REPO_ROOT / "disturbance/baselines/mass.yaml"


def _load_attr(rel_module: str, attr: str):
    """Import *attr* from a test module by path, without importing the suite."""
    import importlib.util

    path = _REPO_ROOT / rel_module
    spec = importlib.util.spec_from_file_location(f"_baseline_{attr}", path)
    assert spec and spec.loader, f"cannot load {rel_module}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, attr)


def _paths_of(entries) -> list[str]:
    """The ``src/...`` prefix of each ``path::qualname::primitive`` key."""
    return [key.split("::", 1)[0] for key in entries]


@pytest.mark.parametrize(
    ("name", "rel_module", "attr"), _CODE_BASELINES, ids=[b[0] for b in _CODE_BASELINES]
)
def test_baseline_keys_name_a_file_that_exists(
    name: str, rel_module: str, attr: str
) -> None:
    entries = _load_attr(rel_module, attr)
    dead = sorted({p for p in _paths_of(entries) if not (_REPO_ROOT / p).is_file()})
    assert not dead, (
        f"{name} holds keys whose file no longer exists: {dead}.\n"
        "A shrink-only ratchet reads the disappearance as progress, so a "
        "decomposition that merely RE-KEYED these entries is filed as a fix. "
        "Re-point each key at the file the scanner now emits, or remove it if "
        "the site is genuinely gone."
    )


@pytest.mark.parametrize(
    ("name", "rel_module", "attr"), _CODE_BASELINES, ids=[b[0] for b in _CODE_BASELINES]
)
def test_baseline_is_not_empty(name: str, rel_module: str, attr: str) -> None:
    """An empty baseline makes the assertion above vacuous rather than clean."""
    assert _load_attr(rel_module, attr), (
        f"{name} is empty — the resolution guard above can never fail. If the "
        "ratchet really has shrunk to zero, delete it rather than leaving a "
        "guard with no subject."
    )


def _mass_class_keys() -> list[str]:
    text = _MASS_BASELINE.read_text()
    return re.findall(r"^  (src/[^\s:]+):", text, re.MULTILINE)


def test_mass_baseline_class_keys_name_a_file_that_exists() -> None:
    """``erosion/mass`` keys are ``src/<path>.py:<Class>``."""
    keys = _mass_class_keys()
    assert keys, f"no class keys parsed from {_MASS_BASELINE} — guard is vacuous"
    dead = sorted({k for k in keys if not (_REPO_ROOT / k).is_file()})
    assert not dead, (
        f"mass.yaml holds class keys whose file no longer exists: {dead}. "
        "Decomposition re-keys an entry; the shrink-only ratchet then reads "
        "the old key's disappearance as the class having shrunk."
    )


def test_the_detector_actually_fires(tmp_path: Path) -> None:
    """Negative control — every baseline resolves today, so prove it can fail."""
    assert not (_REPO_ROOT / "src/definitely_not_a_module_11673.py").is_file()
    fabricated = ["src/definitely_not_a_module_11673.py::Thing.method::spawn"]
    dead = [p for p in _paths_of(fabricated) if not (_REPO_ROOT / p).is_file()]
    assert dead == ["src/definitely_not_a_module_11673.py"]


def test_a_package_member_key_is_accepted() -> None:
    """Real entries already name package members; those must stay green."""
    live = "src/dashboard_routes/_routes.py"
    assert (_REPO_ROOT / live).is_file(), (
        f"{live} moved — update this control so it keeps testing what it says"
    )
    assert not [
        p for p in _paths_of([f"{live}::f::g"]) if not (_REPO_ROOT / p).is_file()
    ]
