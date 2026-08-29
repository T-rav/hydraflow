"""P2 — DDD, Ports & Adapters, Clean Architecture (ADR-0044)."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from .. import layout
from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding


@register("P2.1")
def _src_dir_exists(ctx: CheckContext) -> Finding:
    src = ctx.src_root()
    if src.is_dir():
        return finding("P2.1", Status.PASS)
    return finding("P2.1", Status.FAIL, f"missing: {ctx.rel(src)}")


@register("P2.2")
def _ports_module_has_protocol(ctx: CheckContext) -> Finding:
    ports = ctx.src_module("ports")
    if not ports.exists():
        return finding("P2.2", Status.FAIL, f"{ctx.rel(ports)} missing")
    protocols = _count_protocol_classes(ports)
    if protocols >= 1:
        return finding("P2.2", Status.PASS, f"{protocols} Protocol(s) defined")
    return finding("P2.2", Status.FAIL, f"{ctx.rel(ports)} defines no Protocol classes")


@register("P2.2a")
def _ports_cover_boundaries(ctx: CheckContext) -> Finding:
    """At least two Protocols = at least two boundaries modelled as ports.

    Only one Protocol is the strongest early signal that `AsyncMock` is
    being used instead of ports for other boundaries. A hard FAIL would be
    too aggressive for greenfield repos; emit a WARN so the gap is visible.
    """
    ports = ctx.src_module("ports")
    if not ports.exists():
        return finding("P2.2a", Status.FAIL, f"{ctx.rel(ports)} missing")
    protocols = _count_protocol_classes(ports)
    if protocols >= 2:
        return finding("P2.2a", Status.PASS, f"{protocols} Protocols cover boundaries")
    return finding(
        "P2.2a",
        Status.WARN,
        f"only {protocols} Protocol in {ctx.rel(ports)} — likely boundaries are AsyncMock-faked",
    )


@register("P2.5")
def _composition_root_exists(ctx: CheckContext) -> Finding:
    candidates = [
        ctx.src_module("service_registry"),
        ctx.src_module("composition_root"),
        ctx.src_module("container"),
    ]
    for path in candidates:
        if path.exists():
            return finding("P2.5", Status.PASS, f"composition root: {ctx.rel(path)}")
    probed = ", ".join(ctx.rel(path) for path in candidates)
    return finding("P2.5", Status.FAIL, f"no composition root found (tried {probed})")


#: Third-party distributions a domain module may import without losing purity.
#:
#: These are DECLARATIVE modelling libraries: they describe the shape of data
#: and perform no I/O of their own. Pydantic in particular MUST be allowed —
#: ADR-0044 P2 (and sibling check P2.8) explicitly bless Pydantic models as
#: domain DTOs, so banning the import here would make the two checks
#: contradict each other.
_DOMAIN_SAFE_THIRD_PARTY = frozenset(
    {"pydantic", "typing_extensions", "attr", "attrs", "annotated_types"}
)

#: Name conventions that mark a first-party module as infrastructure.
#:
#: Convention-based on purpose. #8383 deleted the previous layer checker
#: because its hardcoded LAYER_MAP "can't generalize to the projects HydraFlow
#: manages", and prescribed that "any future arch-drift mechanism should be
#: convention-based or per-repo config". A suffix is a convention; a map of
#: this repo's directory names is not.
_INFRA_NAME_SUFFIXES = ("_loop", "_runner", "_adapter", "_client", "_gateway")
_INFRA_NAME_EXACT = frozenset({"server"})


@register("P2.7")
def _domain_layer_purity(ctx: CheckContext) -> Finding:
    """Domain modules import no infrastructure, runners, or adapter SDKs.

    Re-implemented in place of the deleted ``scripts/check_layer_imports.py``
    shell-out. The old body ran that script and reported NA when it was
    missing, which it had been since #8383 — so P2.7 never once verified
    domain purity despite being the check ADR-0044 calls "the load-bearing
    invariant".

    The rule is convention-based rather than topology-based, which is what
    #8383 asked any replacement to be: an import is a violation when its root
    module is third-party and not a declarative modelling library, or when it
    is first-party and named like infrastructure. Both tests generalise to any
    repo the audit is pointed at; neither needs a per-repo layer map.
    """
    domain_files = _domain_files(ctx)
    if not domain_files:
        return finding(
            "P2.7",
            Status.NA,
            f"no {ctx.rel(ctx.src_module('models'))} or "
            f"{ctx.rel(ctx.src_dir('domain'))}/ — this repo declares no domain layer",
        )
    first_party = _first_party_names(ctx)
    violations: list[str] = []
    for path in domain_files:
        for lineno, root, kind in _imported_roots(path):
            reason = _impurity(root, kind, first_party)
            if reason:
                violations.append(f"{ctx.rel(path)}:{lineno} imports {root} ({reason})")
    if violations:
        sample = "; ".join(violations[:5])
        more = f" (+{len(violations) - 5} more)" if len(violations) > 5 else ""
        return finding(
            "P2.7",
            Status.FAIL,
            f"{len(violations)} impure import(s) in the domain layer: {sample}{more}",
        )
    return finding(
        "P2.7",
        Status.PASS,
        f"{len(domain_files)} domain module(s) import no infrastructure or adapter SDKs",
    )


def _impurity(root: str, kind: str, first_party: frozenset[str]) -> str | None:
    """Why importing *root* breaks domain purity, or None if it is fine."""
    if kind == "relative":
        return None  # domain importing its own package is the point
    if root in sys.stdlib_module_names:
        return None
    if root in first_party:
        if root in _INFRA_NAME_EXACT or root.endswith(_INFRA_NAME_SUFFIXES):
            return "first-party infrastructure/runner module"
        return None
    if root in _DOMAIN_SAFE_THIRD_PARTY:
        return None
    return "third-party adapter SDK"


def _first_party_names(ctx: CheckContext) -> frozenset[str]:
    """Top-level module/package names importable from this repo's source tree."""
    src = ctx.src_root()
    if not src.is_dir():
        return frozenset()
    names = {p.stem for p in src.glob("*.py")}
    names |= {p.name for p in src.iterdir() if p.is_dir() and _is_identifier(p.name)}
    for package in layout.root_packages(ctx.root):
        pkg_dir = src / package
        names.add(package)
        if pkg_dir.is_dir():
            names |= {p.stem for p in pkg_dir.glob("*.py")}
            names |= {
                p.name
                for p in pkg_dir.iterdir()
                if p.is_dir() and _is_identifier(p.name)
            }
    return frozenset(names - {"__pycache__"})


def _is_identifier(name: str) -> bool:
    return name.isidentifier()


def _imported_roots(path: Path) -> list[tuple[int, str, str]]:
    """(lineno, root module name, "absolute"|"relative") for every import."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                (node.lineno, alias.name.split(".")[0], "absolute")
                for alias in node.names
            ]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((node.lineno, node.module or "", "relative"))
            elif node.module:
                found.append((node.lineno, node.module.split(".")[0], "absolute"))
    return found


@register("P2.8")
def _domain_types_carry_behaviour(ctx: CheckContext) -> Finding:
    """Warn when domain classes that are NOT DTOs have no behaviour.

    ADR-0044 P2: "anaemic Pydantic models that only hold fields belong in
    DTOs, not the domain." So we explicitly exclude Pydantic BaseModel
    subclasses, TypedDicts, and `@dataclass(frozen=True)` value objects
    from the anaemic check — they are deliberately data-only. What we care
    about is domain entities that ought to model behaviour but don't.
    """
    candidates = _domain_files(ctx)
    if not candidates:
        return finding(
            "P2.8",
            Status.NA,
            f"no {ctx.rel(ctx.src_module('models'))} or "
            f"{ctx.rel(ctx.src_dir('domain'))}/ — nothing to sample",
        )
    anaemic = 0
    entity_total = 0
    for path in candidates:
        for cls in _public_classes(path):
            if _looks_like_dto(cls):
                continue
            entity_total += 1
            if not _has_real_method(cls):
                anaemic += 1
    if entity_total == 0:
        return finding(
            "P2.8",
            Status.NA,
            "all sampled domain classes are DTOs (Pydantic / TypedDict / frozen dataclass) — nothing to evaluate",
        )
    ratio = anaemic / entity_total
    if ratio < 0.6:
        return finding(
            "P2.8",
            Status.PASS,
            f"{anaemic}/{entity_total} non-DTO domain classes anaemic ({ratio:.0%})",
        )
    return finding(
        "P2.8",
        Status.WARN,
        f"{anaemic}/{entity_total} non-DTO domain classes have no behaviour — logic may be leaking to application/infra",
    )


_DTO_BASE_NAMES = {
    "BaseModel",
    "TypedDict",
    "NamedTuple",
    "Protocol",
    "Enum",
    "IntEnum",
    "StrEnum",
    "Flag",
}


def _looks_like_dto(cls: ast.ClassDef) -> bool:
    """Classes that are *designed* to be data holders are exempt from P2.8.

    Matches:
      - Pydantic `BaseModel` (direct or via `pydantic.BaseModel`)
      - `TypedDict`, `NamedTuple`, `Protocol`, `Enum`, `IntEnum`, `StrEnum`, `Flag`
      - Any `@dataclass`-decorated class (frozen or not — plain dataclasses
        are idiomatic parameter-grouping DTOs in Python)
    """
    for base in cls.bases:
        name = ""
        if isinstance(base, ast.Name):
            name = base.id
        elif isinstance(base, ast.Attribute):
            name = base.attr
        if name in _DTO_BASE_NAMES or name.endswith("BaseModel"):
            return True
    return any(_is_dataclass(decorator) for decorator in cls.decorator_list)


def _is_dataclass(decorator: ast.expr) -> bool:
    """True for `@dataclass`, `@dataclass(...)`, or `dataclasses.dataclass` forms."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "dataclass"
    if isinstance(target, ast.Attribute):
        return target.attr == "dataclass"
    return False


@register("P2.9")
def _ubiquitous_language(ctx: CheckContext) -> Finding:
    """Warn when CLAUDE.md ubiquitous-language terms don't appear in the wiki.

    CLAUDE.md is a lean ToC; it lists a short ubiquitous-language vocabulary
    operators must use without paraphrasing. Those names must appear in the
    wiki's architecture topic so an agent looking up any of them lands on
    real context. The reverse direction (every wiki term must appear in
    CLAUDE.md) was load-bearing under the old layout where CLAUDE.md
    duplicated architecture content; the new layout intentionally moves
    architecture into the wiki, so the check now flows ToC → wiki.
    """
    # Architecture content lived in a single ``architecture.md`` until PR
    # #8462 split it into focused topic files (``architecture-layers.md``,
    # etc.). Read every ``architecture*.md`` so a term documented in a
    # sub-topic still resolves. The residual ``architecture.md`` remains
    # the entry point — it carries the ubiquitous-language reference table
    # — but is no longer the sole source of truth.
    wiki = ctx.root / "docs" / "wiki"
    arch_files = sorted(wiki.glob("architecture*.md"))
    claude = ctx.root / "CLAUDE.md"
    if not arch_files or not claude.exists():
        return finding(
            "P2.9",
            Status.NA,
            "architecture wiki topic or CLAUDE.md missing — upstream P1 checks cover this",
        )
    claude_terms = _capitalised_terms(
        claude.read_text(encoding="utf-8", errors="replace")
    )
    arch_text = "\n".join(
        f.read_text(encoding="utf-8", errors="replace") for f in arch_files
    )
    if len(claude_terms) < 3:
        return finding(
            "P2.9",
            Status.NA,
            f"only {len(claude_terms)} candidate terms in CLAUDE.md — sample too small",
        )
    missing = [t for t in claude_terms if t not in arch_text]
    ratio_missing = len(missing) / len(claude_terms)
    if ratio_missing < 0.5:
        return finding(
            "P2.9",
            Status.PASS,
            f"{len(claude_terms) - len(missing)}/{len(claude_terms)} ToC terms covered by wiki",
        )
    sample = ", ".join(missing[:5])
    return finding(
        "P2.9",
        Status.WARN,
        f"{len(missing)}/{len(claude_terms)} CLAUDE.md terms absent from wiki ({sample})",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_protocol_classes(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _inherits_protocol(node):
            count += 1
    return count


def _inherits_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _domain_files(ctx: CheckContext) -> list[Path]:
    candidates: list[Path] = []
    models = ctx.src_module("models")
    if models.exists():
        candidates.append(models)
    domain_dir = ctx.src_dir("domain")
    if domain_dir.is_dir():
        candidates.extend(sorted(domain_dir.glob("*.py")))
    return candidates


def _public_classes(path: Path) -> list[ast.ClassDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    ]


def _has_real_method(cls: ast.ClassDef) -> bool:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            return True
    return False


_CAMEL_CASE = re.compile(r"\b([A-Z][a-z]+[A-Z][A-Za-z]+)\b")


def _capitalised_terms(text: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in _CAMEL_CASE.finditer(text):
        term = match.group(1)
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms
