"""Core types for the audit pipeline.

Kept deliberately small: `CheckSpec` is the declarative row parsed from the
ADR; `Finding` is the result of running one check; `CheckContext` is the
execution environment handed to each check function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from . import layout


class Severity(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    BEHAVIORAL = "BEHAVIORAL"
    CULTURAL = "CULTURAL"


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NA = "NA"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass(frozen=True)
class CheckSpec:
    """A single row from an ADR-0044 check table."""

    check_id: str
    severity: Severity
    source: str
    what: str
    remediation: str
    principle: str  # e.g. "P1"


@dataclass
class Finding:
    """The result of running one check."""

    check_id: str
    status: Status
    severity: Severity
    principle: str
    source: str
    what: str
    remediation: str
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "status": self.status.value,
            "severity": self.severity.value,
            "principle": self.principle,
            "source": self.source,
            "what": self.what,
            "remediation": self.remediation,
            "message": self.message,
        }


@dataclass
class CheckContext:
    """Execution context passed to every check function.

    Checks read from `root` (the target repo). They do not mutate anything.

    Source modules are resolved through :meth:`src_module` / :meth:`src_dir`,
    never as a literal ``ctx.root / "src" / "<name>.py"``: the greenfield
    kernel writer stamps ``src/<pkg>/`` and a flat literal is blind to every
    repo it creates (#11709). See :mod:`scripts.hydraflow_audit.layout`.
    """

    root: Path
    is_orchestration_repo: bool = False
    has_ui: bool = False
    extras: dict = field(default_factory=dict)
    #: Root packages under ``src/``, resolved once per context. One audit run
    #: sees one layout; the target repo does not change underneath it.
    _src_packages: tuple[str, ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @property
    def src_packages(self) -> tuple[str, ...]:
        """Root package names under ``src/`` — empty for a flat repo."""
        if self._src_packages is None:
            self._src_packages = layout.root_packages(self.root)
        return self._src_packages

    def src_module(self, name: str) -> Path:
        """Resolve source module ``name`` across flat and packaged layouts.

        ``ctx.src_module("ports")`` -> the first of ``src/ports.py``,
        ``src/<pkg>/ports.py`` that exists. When neither does, the returned
        path is the one this repo's layout implies, so ``f"{ctx.rel(p)}
        missing"`` names something actionable.
        """
        return layout.src_module(self.root, name, self.src_packages)

    def src_dir(self, *parts: str) -> Path:
        """Resolve a source *directory* — ``src_dir("mockworld", "fakes")``."""
        return layout.src_dir(self.root, *parts, packages=self.src_packages)

    def rel(self, path: Path) -> str:
        """``path`` as a posix path relative to the repo root, for messages."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()
