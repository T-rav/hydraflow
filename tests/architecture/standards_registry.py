"""The standards in ``docs/standards/`` as data, and what enforces each one.

Every standard directory carries a ``standard.yaml`` whose ``id`` is the
directory name and whose ``enforced_by`` lists the pytest paths that hold that
standard's prose to a machine-readable artifact. The id is what makes a
standard *referenceable*: ``charter.yaml``'s ``articles.standards`` entries
(#11748) resolve against it, and an id that does not resolve to a directory is
a declaration with no subject.

Two writers, one set — the same shape as
``test_factory_autonomy_policy_drift``. ``standard.yaml`` is normative; the
README's ``Enforced by`` block is commentary that must agree with it. The
properties in ``test_standards_registry.py`` redden when the two disagree in
either direction, and again when a cited path stops being collected by pytest.
That last one is the point: a citation to a gate that exists but never runs is
a citation to nothing (``docs/standards/vitals_conformance/README.md`` —
"a conformance check that stops running must fail, not pass").

Discovery here is by directory listing rather than by hand-registration, which
is the opposite of ``path_membership_registry`` and ``vitals_conformance_
registry`` and deliberately so: those register *checks*, where a check nobody
listed is a check nobody classified. This registers *directories*, where the
filesystem already is the enumeration and a hand list could silently stop
covering one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "ENFORCED_BY_BEGIN",
    "ENFORCED_BY_END",
    "Standard",
    "StandardsRegistryError",
    "has_enforced_by_block",
    "readme_enforced_by",
    "registered_standards",
    "repo_root",
    "standard_directories",
    "standards_dir",
]

#: Delimiters of the README block that cites this standard's enforcing tests.
ENFORCED_BY_BEGIN = "<!-- standard:enforced-by -->"
ENFORCED_BY_END = "<!-- /standard:enforced-by -->"

#: One backticked repo-relative path per bullet inside the block.
_CITATION_RE = re.compile(r"^-\s+`([^`]+)`")

_STANDARD_FILENAME = "standard.yaml"


class StandardsRegistryError(RuntimeError):
    """Raised when a ``standard.yaml`` cannot be read as a standard."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def standards_dir() -> Path:
    return repo_root() / "docs" / "standards"


def standard_directories() -> tuple[str, ...]:
    """Every directory under ``docs/standards/``, sorted.

    Derived from disk, so a standard added without a ``standard.yaml`` shows
    up as a missing member rather than as nothing at all.
    """
    root = standards_dir()
    return tuple(sorted(p.name for p in root.iterdir() if p.is_dir()))


@dataclass(frozen=True, slots=True)
class Standard:
    """One ``docs/standards/<id>/`` directory and its declared enforcement."""

    id: str
    """Declared in ``standard.yaml``. MUST equal ``directory``."""

    directory: str
    """The directory name on disk — the thing an id has to resolve to."""

    enforced_by: tuple[str, ...]
    """Repo-relative pytest paths. Each must exist AND be collected."""

    yaml_path: Path
    readme_path: Path


def _load_one(directory: str) -> Standard:
    yaml_path = standards_dir() / directory / _STANDARD_FILENAME
    if not yaml_path.exists():
        raise StandardsRegistryError(
            f"docs/standards/{directory}/ has no {_STANDARD_FILENAME} — every "
            "standard needs a resolvable id so charter.yaml can point at it"
        )
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StandardsRegistryError(f"{yaml_path}: unreadable ({exc})") from exc
    if not isinstance(raw, dict):
        raise StandardsRegistryError(f"{yaml_path}: expected a mapping")
    declared_id = raw.get("id")
    if not isinstance(declared_id, str) or not declared_id:
        raise StandardsRegistryError(f"{yaml_path}: missing a non-empty `id`")
    enforced = raw.get("enforced_by") or []
    if not isinstance(enforced, list) or any(not isinstance(e, str) for e in enforced):
        raise StandardsRegistryError(
            f"{yaml_path}: `enforced_by` must be a list of repo-relative paths"
        )
    return Standard(
        id=declared_id,
        directory=directory,
        enforced_by=tuple(enforced),
        yaml_path=yaml_path,
        readme_path=standards_dir() / directory / "README.md",
    )


def registered_standards() -> tuple[Standard, ...]:
    """Every standard on disk, in directory order."""
    return tuple(_load_one(name) for name in standard_directories())


def readme_enforced_by(standard: Standard) -> tuple[str, ...]:
    """Repo-relative paths cited inside the README's ``Enforced by`` block.

    Returns ``()`` when the block is absent, which the drift property reports
    as a missing block rather than as an empty agreement — an absent block and
    an empty ``enforced_by`` would otherwise agree with each other.
    """
    text = standard.readme_path.read_text(encoding="utf-8")
    if ENFORCED_BY_BEGIN not in text or ENFORCED_BY_END not in text:
        return ()
    body = text.split(ENFORCED_BY_BEGIN, 1)[1].split(ENFORCED_BY_END, 1)[0]
    cited: list[str] = []
    for line in body.splitlines():
        match = _CITATION_RE.match(line.strip())
        if match:
            cited.append(match.group(1))
    return tuple(cited)


def has_enforced_by_block(standard: Standard) -> bool:
    """Whether the README carries the block at all (vs. an empty one)."""
    text = standard.readme_path.read_text(encoding="utf-8")
    return ENFORCED_BY_BEGIN in text and ENFORCED_BY_END in text
