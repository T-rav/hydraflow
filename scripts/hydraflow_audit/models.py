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
    """Outcome of one check.

    ``NA`` and ``INERT`` are the two ways a check can decline to produce a
    verdict, and the difference is the whole point of keeping them apart:

    ``NA``
        The check RAN, looked at its subject, and the subject legitimately
        does not apply to this repo — no ``src/ui`` in a backend service, no
        PR context outside CI. Not a failure. Every check allowed to reach
        this state is enumerated, with its reason, in
        :mod:`scripts.hydraflow_audit.na_justifications`.
    ``INERT``
        The check could NOT look at its subject — the artifact it measures is
        gone, or the tool it shells out to did not complete. An absent subject
        is not a passing subject, so this fails the gate.

    ``INERT`` is the mirror of ``NOT_IMPLEMENTED``: that one is an ADR row with
    no code behind it, this one is code with no subject in front of it. Both
    mean the audit is advertising a check it does not perform, and both are
    loud (#8383/#8386 — P2.3/P2.4/P2.6/P2.7 shelled out to a
    ``scripts/check_layer_imports.py`` that was deleted less than four hours
    after they were merged, and reported ``NA`` ever after while ``make audit``
    stayed green).
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NA = "NA"
    INERT = "INERT"
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

    def src_root(self) -> Path:
        """The source directory — the root of a RECURSIVE scan.

        Layout-agnostic already: ``rglob`` from here reaches ``src/<pkg>/**``
        too. Spelled as a method rather than ``ctx.root / "src"`` so the
        literal lives in exactly one module and the #11709 ratchet can gate on
        the literal instead of on AST shapes it would have to enumerate.
        """
        return layout.src_root(self.root)

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
