"""Regression: the agent/sandbox image must ship the auto-agent prompts (#11590).

Before this pin every in-container auto-agent spawn died with
``FileNotFoundError`` on ``_default.md``: the container runs HydraFlow from
``/opt/hydraflow/src``, and ``Dockerfile.agent`` copied ``src`` and ``tests``
but not the ``prompts/`` tree that ``preflight.runner`` reads. Invisible while
the light lane defaulted off, because no sandbox scenario reached a spawn.

#11589 moved the prompts under ``src/hydraflow_resources/`` and made them
package data, so ``COPY src`` now carries them and the standalone ``COPY
prompts`` line is gone. **The invariant moved; it did not disappear** — the
prompts must still land at the path the resolver computes at runtime. Pinning
one literal destination (``/opt/hydraflow/prompts``) only ever asserted the
old resolver's answer, so this pins the two sides against each other instead:
the tree ``preflight.runner`` reads must be inside something the image copies,
and it must land exactly where ``package_resources.package_root()`` will look
for it given the image's own ``PYTHONPATH``. Either side moving alone fails.
"""

from __future__ import annotations

import re
from pathlib import Path

from package_resources import RESOURCE_PACKAGE, resource_dir
from preflight.runner import _PROMPT_DIR

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile.agent"
_COPY_RE = re.compile(r"^COPY\s+(?:--chown=\S+\s+)?(\S+)\s+(\S+)\s*$", re.MULTILINE)
_PYTHONPATH_RE = re.compile(r"^ENV PYTHONPATH=(\S+)\s*$", re.MULTILINE)

#: The prompt tree the runtime reads, as a repo-relative path.
_PROMPTS_REL = _PROMPT_DIR.relative_to(_REPO_ROOT)


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _copied_into_opt_hydraflow() -> dict[str, str]:
    """``{source path in the build context: destination in the image}``."""
    return {
        src: dst
        for src, dst in _COPY_RE.findall(_dockerfile())
        if dst.startswith("/opt/hydraflow/")
    }


def _image_path_of(rel: Path) -> str | None:
    """Where *rel* (repo-relative) lands in the image, or ``None`` if uncopied.

    Mechanism-agnostic: satisfied by ``COPY src`` carrying the tree today, and
    equally by a standalone ``COPY`` of the tree itself.
    """
    for src, dst in _copied_into_opt_hydraflow().items():
        source = Path(src)
        if rel == source or source in rel.parents:
            return f"{dst}/{rel.relative_to(source).as_posix()}".rstrip("/")
    return None


def _container_package_root() -> str | None:
    """The image's ``package_root()`` — the copied ``src`` tree, on PYTHONPATH."""
    match = _PYTHONPATH_RE.search(_dockerfile())
    if match is None:
        return None
    copied_src = _copied_into_opt_hydraflow().get("src")
    entries = match.group(1).split(":")
    return copied_src if copied_src in entries else None


def test_agent_image_copies_the_tree_the_prompt_resolver_reads() -> None:
    """Some COPY carries the auto-agent prompts into the image (#11590)."""
    assert _image_path_of(_PROMPTS_REL) is not None, (
        f"Dockerfile.agent copies nothing containing {_PROMPTS_REL.as_posix()}, "
        "so every in-container auto-agent spawn dies on _default.md (#11590). "
        f"Copied into /opt/hydraflow/: {sorted(_copied_into_opt_hydraflow())}"
    )


def test_copied_prompts_land_where_the_resolver_will_look() -> None:
    """The image path and ``package_root()``'s answer must be the same path."""
    package_root = _container_package_root()
    assert package_root is not None, (
        "Dockerfile.agent no longer puts the copied src/ tree on PYTHONPATH; "
        "package_resources.package_root() would not resolve to it in the image"
    )
    expected = (
        f"{package_root}/{RESOURCE_PACKAGE}/"
        f"{_PROMPT_DIR.relative_to(resource_dir('prompts').parent).as_posix()}"
    )
    assert _image_path_of(_PROMPTS_REL) == expected


def test_every_auto_agent_playbook_is_a_tracked_file() -> None:
    """The prompts the resolver points at are really on disk."""
    missing = [
        name
        for name in ("_default.md", "_envelope.md", "auto-light.md")
        if not (_PROMPT_DIR / name).is_file()
    ]
    assert missing == [], f"auto-agent prompts missing from {_PROMPT_DIR}: {missing}"
