"""Citation extraction + AST verification + fuzzy suggestion for
:mod:`wiki_rot_detector_loop` (spec §4.9).

Three extraction patterns, one AST verifier, one grep fallback, one
fuzzy matcher. Each function is side-effect-free and unit-testable in
isolation — the loop composes them per cite.
"""

from __future__ import annotations

import ast
import difflib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hydraflow.wiki_rot_citations")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Style-A: ``path/to/module.py:symbol`` — the HydraFlow house style.
_STYLE_A_RE = re.compile(r"\b([\w./-]+\.py):(\w+)")

# Style-B: ``src.module.Class`` — dotted Python import path anchored to
# the ``src`` root. Anchoring to ``src`` prevents false positives on
# ordinary dotted prose (``big.bad.wolf``). The final segment is the
# symbol; everything before is the module dotted path.
_STYLE_B_RE = re.compile(r"\b(src(?:\.\w+)+)\b")

# Style-C: bare identifiers within ``` ```python ``` ``` fences that look
# like cites (def / class / call sites). Hints only — ambiguous without
# context.
_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*[:(]", re.MULTILINE)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# Style-D: a bare backticked tool/script name in *imperative* prose — e.g.
# "Run ``wiki_lesson_coverage``", "invoke ``foo_bar.py``". A bare cite carries
# no module/symbol pair (Style-A/B do), so it can't be AST-verified; it is
# resolved by *presence* against a corpus of module/script basenames + defined
# symbols (:func:`build_symbol_corpus` / :func:`resolve_bare_cite`).
#
# Precision is the whole game here (#10762, #10768). An ungated scan of
# ``repo_wiki`` for backticked snake_case tokens flags ~52 identifiers absent
# from the code surface, but roughly half are ordinary prose that merely
# *looks* like an identifier (``cancel_fn``, ``abandoned_at``, ``setup_method``,
# ``bank_order``). Restricting extraction to imperative "run / invoke /
# execute" position — the verb directly governing the backtick, with only a
# short connective ("the", "python", "script"…) allowed between — collapses
# that to the genuine dead-tool cites only. Empirically it flags exactly one
# token corpus-wide: ``wiki_lesson_coverage`` (issue #10754's phantom tool).
# Bare filename references in non-imperative prose (illustrative examples of a
# problem, e.g. "the untracked draft ``test_issue_10411.py``") are deliberately
# NOT flagged — they are examples, not runnable-tool cites.
_STYLE_D_VERB = (
    r"(?:run|runs|running|invoke|invokes|invoking|execute|executes|executing)"
)
_STYLE_D_CONNECTIVE = r"(?:the|a|an|python3?|script|tool|command|make|via|using)"
_STYLE_D_RE = re.compile(
    rf"(?i)\b{_STYLE_D_VERB}\b(?:\s+{_STYLE_D_CONNECTIVE})*\s+`([^`\n]+)`"
)

# Shape gate: a snake_case identifier with at least one underscore. Requiring
# an underscore keeps bare single prose words (``run``, ``print``) out of the
# candidate set without a large denylist.
_BARE_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

# Script suffixes stripped for basename resolution — ``foo.py`` and ``foo``
# resolve to the same module stem.
_BARE_SCRIPT_SUFFIXES: tuple[str, ...] = (".py", ".sh")

# Documentation metavariables — placeholder tool/module names used to teach the
# cite grammar (including the wiki entry that documents Style-D itself). They
# never name a real tool, so they must never self-report as broken cites.
_BARE_METAVARS: frozenset[str] = frozenset(
    {
        "my_module",
        "my_tool",
        "my_script",
        "your_module",
        "some_module",
        "some_tool",
        "some_script",
        "some_function",
        "some_missing_tool",  # gotchas/1186's Style-D grammar example (#10754)
        "snake_case",
        "foo_bar",
        "foo_baz",
    }
)


def _bare_basename(token: str) -> str:
    """Strip a trailing ``.py`` / ``.sh`` so ``foo.py`` resolves as ``foo``."""
    for suffix in _BARE_SCRIPT_SUFFIXES:
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


@dataclass(frozen=True)
class Cite:
    """A single cite candidate extracted from a wiki entry.

    ``module`` is either a slashed file path (Style-A) or a dotted Python
    path (Style-B / C).  ``style`` indicates which extractor produced it.
    ``raw`` is the verbatim substring for display in issue bodies.
    """

    module: str
    symbol: str
    style: str  # "colon" | "dotted" | "fenced_hint" | "bare"
    raw: str

    def module_as_path(self) -> str:
        """Return ``module`` normalised to a slashed ``.py`` path.

        Style-A is already slashed; Style-B is dotted (``src.foo.bar``
        → ``src/foo/bar.py``); Style-C (fence hint) and Style-D (bare
        imperative cite) have no module path and return an empty string —
        callers must skip AST verification for both (a bare cite resolves
        via :func:`resolve_bare_cite`, a hint is context-only).
        """
        if self.style == "colon":
            return self.module
        if self.style == "dotted":
            return self.module.replace(".", "/") + ".py"
        return ""


# Documentation metavariables — placeholder symbol names that only ever
# appear in *format-example* cites used to explain the cite grammar in prose
# (``path.py:symbol``, ``src.module.Class``). They never name a real code
# symbol. See :func:`_is_placeholder_cite` (#10595).
_METAVAR_SYMBOLS: frozenset[str] = frozenset(
    {"symbol", "some_symbol", "Class", "module"}
)

# Placeholder module tokens — illustrative paths that never name a real
# source file. Paired with a metavariable symbol they form a self-referential
# documentation example, not a broken cite (#10595).
_PLACEHOLDER_MODULES: frozenset[str] = frozenset(
    {"path.py", "path/to/file.py", "path/to/module.py", "src.module"}
)


def _is_placeholder_cite(module: str, symbol: str) -> bool:
    """Return ``True`` iff ``module``/``symbol`` is a documentation placeholder.

    The wiki entry that documents the rot detector itself explains the cite
    grammar with the literal examples ``path.py:symbol`` (Style-A) and
    ``src.module.Class`` (Style-B). ``extract_cites`` used to emit both as
    real cites; neither can ever resolve, so ``WikiRotDetectorLoop`` reported
    its own docs as rotten forever and escalated them — a permanent
    self-referential false-positive class (#10595).

    A cite is a placeholder only when it pairs a placeholder module token with
    a metavariable symbol — the ``AND`` keeps genuine broken cites reported: a
    real-looking module with a metavariable-shaped symbol (``real.py:Class``),
    or a placeholder module with a real symbol (``path.py:handle``), still
    surfaces.
    """
    return module in _PLACEHOLDER_MODULES and symbol in _METAVAR_SYMBOLS


def extract_cites(text: str) -> list[Cite]:
    """Extract Style-A + Style-B + Style-D hard cites from markdown/prose.

    Deduplicated by ``(module, symbol, style)``.  Fenced-code hints
    (Style-C) are **excluded** — see :func:`extract_fenced_hints`.
    Documentation placeholder cites (:func:`_is_placeholder_cite`) are
    likewise excluded so the detector never flags its own format examples.

    Style-D (bare backticked tool/script name in imperative position) carries
    no module/symbol pair, so its ``Cite`` has ``module=""`` and
    ``style="bare"``; the caller resolves it by presence via
    :func:`resolve_bare_cite` against :func:`build_symbol_corpus` rather than
    AST verification.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Cite] = []

    for m in _STYLE_A_RE.finditer(text):
        module = m.group(1)
        symbol = m.group(2)
        # A purely-numeric tail (``path.py:141``) is a *line reference*, not
        # a symbol cite. ``\w+`` in ``_STYLE_A_RE`` matches digits, so these
        # slipped through as bogus symbol cites that can never resolve via
        # ``verify_cite_ast`` — a permanent wiki-rot false-positive class
        # (#10591). Python identifiers never start with a digit, so skip
        # them here; genuine ``path.py:Symbol`` tails are unaffected.
        if symbol.isdigit():
            continue
        if _is_placeholder_cite(module, symbol):
            continue
        key = (module, symbol, "colon")
        if key in seen:
            continue
        seen.add(key)
        out.append(Cite(module=module, symbol=symbol, style="colon", raw=m.group(0)))

    for m in _STYLE_B_RE.finditer(text):
        path = m.group(1)
        parts = path.split(".")
        if len(parts) < 2:
            continue
        module = ".".join(parts[:-1])
        symbol = parts[-1]
        # Only treat the last segment as a symbol if it starts with an
        # identifier char — some prose ends in ``src.foo.`` (trailing dot)
        # which the `\b` anchor does not catch.
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", symbol):
            continue
        if _is_placeholder_cite(module, symbol):
            continue
        key = (module, symbol, "dotted")
        if key in seen:
            continue
        seen.add(key)
        out.append(Cite(module=module, symbol=symbol, style="dotted", raw=path))

    for m in _STYLE_D_RE.finditer(text):
        raw = m.group(1).strip()
        base = _bare_basename(raw)
        # Shape gate (snake_case, ≥1 underscore) + metavariable denylist keep
        # ordinary prose and self-referential grammar examples out.
        if not _BARE_SNAKE_RE.match(base):
            continue
        if base in _BARE_METAVARS:
            continue
        key = ("", base, "bare")
        if key in seen:
            continue
        seen.add(key)
        out.append(Cite(module="", symbol=base, style="bare", raw=raw))

    return out


def extract_fenced_hints(text: str) -> list[Cite]:
    """Return Style-C fenced-code hints — bare symbol names inside
    ``` ```python ``` ``` fences.

    Emitted as :class:`Cite` with ``style="fenced_hint"`` and an empty
    ``module`` field.  Callers use these as contextual appendices only;
    they are not verified against the filesystem.
    """
    seen: set[str] = set()
    out: list[Cite] = []

    for fence in _FENCE_RE.finditer(text):
        body = fence.group(1)
        for rx in (_DEF_RE, _CLASS_RE, _CALL_RE):
            for sym_match in rx.finditer(body):
                name = sym_match.group(1)
                if name in seen or name in _BUILTINS_DENY:
                    continue
                seen.add(name)
                out.append(Cite(module="", symbol=name, style="fenced_hint", raw=name))

    return out


# Python builtins and common stdlib names that pollute fenced-hint
# extraction. Suppressed so the issue context doesn't list ``print``,
# ``len`` and friends as "hints".
_BUILTINS_DENY: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "range",
        "enumerate",
        "zip",
        "open",
        "isinstance",
        "type",
        "hasattr",
        "getattr",
        "setattr",
        "repr",
        "id",
        "map",
        "filter",
        "sorted",
        "reversed",
        "sum",
        "min",
        "max",
        "abs",
        "any",
        "all",
        "iter",
        "next",
        "self",
        "cls",
        "True",
        "False",
        "None",
    }
)


# ---------------------------------------------------------------------------
# Shipped-claim extraction (issue #9598)
# ---------------------------------------------------------------------------

# ``json:entry`` machine blocks — the RepoWikiStore house format. Both the
# single-line compiled shape and the multi-line manual shape are captured;
# the JSON body is parsed leniently below.
_JSON_ENTRY_RE = re.compile(r"```json:entry\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class ShippedClaim:
    """A structured "shipped in #NNNN" assertion from a wiki entry.

    Sourced from the ``fixed_in_pr`` field of a ``json:entry`` machine
    block — the one machine-readable shape in the RepoWikiStore format that
    asserts a fix *landed* in a specific PR.  ``code_refs`` carries the
    entry's own corroborating code references (``path.py:symbol`` strings);
    the loop verifies the claim by resolving them against the codebase.

    Provenance footers (``_Source: #NNNN (plan)_``) are deliberately **not**
    shipped claims and are never extracted here.
    """

    pr_ref: str  # e.g. "#8713"
    code_refs: tuple[str, ...]
    raw: str  # verbatim block body, for excerpting in issue bodies


def extract_shipped_claims(text: str) -> list[ShippedClaim]:
    """Extract structured shipped claims (``fixed_in_pr``) from *text*.

    Scans every ``json:entry`` block, parses its JSON body leniently, and
    emits a :class:`ShippedClaim` for each block carrying a non-empty
    ``fixed_in_pr``.  Blocks with malformed JSON, no ``fixed_in_pr``, or a
    blank ``fixed_in_pr`` are skipped — the function never raises on bad
    input.  Deduplicated by ``(pr_ref, code_refs)``.
    """
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[ShippedClaim] = []

    for block in _JSON_ENTRY_RE.finditer(text):
        body = block.group(1)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        pr_ref = data.get("fixed_in_pr")
        if not isinstance(pr_ref, str) or not pr_ref.strip():
            continue
        pr_ref = pr_ref.strip()

        raw_refs = data.get("code_refs", [])
        code_refs: tuple[str, ...] = ()
        if isinstance(raw_refs, list):
            code_refs = tuple(r for r in raw_refs if isinstance(r, str) and r.strip())

        key = (pr_ref, code_refs)
        if key in seen:
            continue
        seen.add(key)
        out.append(ShippedClaim(pr_ref=pr_ref, code_refs=code_refs, raw=body.strip()))

    return out


# ---------------------------------------------------------------------------
# AST verification
# ---------------------------------------------------------------------------


def verify_cite_ast(
    repo_root: Path, module_path: str, symbol: str
) -> tuple[bool, list[str]]:
    """Verify *symbol* exists in *module_path* via AST walk.

    Returns ``(ok, symbols)`` where ``symbols`` is the sorted list of
    defined `FunctionDef` / `AsyncFunctionDef` / `ClassDef` names
    (useful for fuzzy suggestions).  For ``__init__.py`` re-exports
    (``from .x import y``), the verifier opens the referenced module
    once and rescans — depth-1 only; deeper chains fall back to grep.

    Non-Python paths, missing files, and parse errors all return
    ``(False, [])`` — callers treat them as broken cites or route them
    to :func:`verify_cite_grep`.
    """
    if not module_path.endswith(".py"):
        return False, []

    module_file = repo_root / module_path
    if not module_file.is_file():
        return False, []

    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        logger.debug("AST parse failed for %s", module_file, exc_info=True)
        return False, []

    symbols = _collect_defined_symbols(tree)

    if symbol in symbols:
        return True, sorted(symbols)

    # Depth-1 re-export resolution: scan ``from .foo import bar`` lines.
    reexport_hits = _follow_reexports(tree, module_file, symbol)
    if reexport_hits:
        return True, sorted(symbols | reexport_hits)

    return False, sorted(symbols)


def _assign_target_names(target: ast.expr) -> set[str]:
    """Names bound by one assignment target, unpacking tuple/list targets.

    Mirrors ``adr_citation_resolve._assign_target_names`` so the two
    resolvers agree on which module-level names a bare cite may resolve to.
    """
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _assign_target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        names: set[str] = set()
        for elt in target.elts:
            names |= _assign_target_names(elt)
        return names
    return set()


def module_symbols(repo_root: Path, module_path: str) -> frozenset[str]:
    """Public accessor: the resolvable symbol names *module_path* defines.

    Parses ``repo_root / module_path`` once and returns the same symbol set
    :func:`verify_cite_ast` checks a cite against — ``def`` / ``class`` names
    at any depth plus module-level constants. Non-Python paths, missing
    files, and parse errors all return an empty set (never raises).

    Exposed so cross-module callers (``wiki_lesson_coverage``) can build a
    cached symbol index without importing the private
    :func:`_collect_defined_symbols` — the repo's cross-module
    ``_``-prefixed-import gotcha. Re-export following is intentionally *not*
    applied here: a lesson anchor should name a symbol its own cited module
    defines directly.
    """
    if not module_path.endswith(".py"):
        return frozenset()
    module_file = repo_root / module_path
    if not module_file.is_file():
        return frozenset()
    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return frozenset()
    return frozenset(_collect_defined_symbols(tree))


def _collect_defined_symbols(tree: ast.AST) -> set[str]:
    """Return the resolvable symbol names defined by *tree*.

    Two symbol classes are collected:

    * **Defs/classes** — every ``FunctionDef`` / ``AsyncFunctionDef`` /
      ``ClassDef`` at *any* depth (walked recursively), so nested helpers
      and methods stay citeable.
    * **Module-level constants** — names bound by *top-level*
      ``ast.Assign`` / ``ast.AnnAssign`` targets (``NAME = ...`` /
      ``NAME: T = ...``, including tuple/list unpacking). Module-level only,
      so a cite to a live constant such as ``src/foo.py:_SURFACE_DEFAULTS``
      resolves (issue #10594) while function-local variables never do.

    Mirrors the bare-name grammar in ``adr_citation_resolve`` so the ADR
    and wiki-rot citation resolvers agree on what a module-level name is.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(node.name)
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                out |= _assign_target_names(tgt)
        elif isinstance(node, ast.AnnAssign):
            out |= _assign_target_names(node.target)
    return out


def _follow_reexports(tree: ast.AST, module_file: Path, symbol: str) -> set[str]:
    """Resolve ``from .x import *`` / ``from .x import symbol`` one level.

    Returns the set of symbols defined in the *re-exported* module if
    that module defines *symbol*; otherwise an empty set.  Deeper chains
    are intentionally not followed — grep fallback covers those.
    """
    module_dir = module_file.parent
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None or node.level == 0:
            continue
        target_parts = node.module.split(".")
        target_file = module_dir.joinpath(*target_parts).with_suffix(".py")
        if not target_file.is_file():
            target_file = module_dir.joinpath(*target_parts, "__init__.py")
            if not target_file.is_file():
                continue
        try:
            sub_tree = ast.parse(target_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        sub_syms = _collect_defined_symbols(sub_tree)
        imported = {a.name for a in node.names}
        if symbol in sub_syms and (symbol in imported or "*" in imported):
            return sub_syms
    return set()


# ---------------------------------------------------------------------------
# Bare-cite corpus resolution (Style-D, issue #10762)
# ---------------------------------------------------------------------------


def build_symbol_corpus(
    repo_root: Path,
    roots: tuple[str, ...] = ("src", "scripts", "tests"),
) -> frozenset[str]:
    """Return the set of names a Style-D bare cite may resolve against.

    Two name classes, so a bare cite for either a script or a symbol resolves:

    * **File stems** — every ``*.py`` / ``*.sh`` basename under *roots*, so a
      bare script cite (``run `foo_bar.py```) resolves to its module file.
    * **Defined symbols** — every ``def`` / ``class`` / module-level
      assignment name across the ``*.py`` tree
      (:func:`_collect_defined_symbols`), so a bare function / CLI-entry cite
      (``run `wiki_lesson_coverage```) resolves.

    Build is tolerant: unreadable, binary, or syntactically-broken files are
    skipped rather than raised, so one bad file cannot abort a weekly tick.
    Self-repo only — a managed repo has no local checkout to resolve against,
    so callers must not build (or consult) a corpus for one.
    """
    names: set[str] = set()
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in _BARE_SCRIPT_SUFFIXES:
                names.add(path.stem)
            if path.suffix == ".py":
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
                    continue
                names |= _collect_defined_symbols(tree)
    return frozenset(names)


def resolve_bare_cite(name: str, corpus: frozenset[str]) -> bool:
    """Return ``True`` iff *name* (a Style-D bare cite) resolves in *corpus*.

    A trailing ``.py`` / ``.sh`` is stripped first so ``foo.py`` and ``foo``
    resolve identically against the module basenames in *corpus*.
    """
    return _bare_basename(name) in corpus


# ---------------------------------------------------------------------------
# Grep fallback (non-Python cites + managed-repo mirrors)
# ---------------------------------------------------------------------------


def verify_cite_grep(repo_root: Path, file_path: str, needle: str) -> bool:
    """Substring search fallback for ``.md`` / ``.json`` / managed-repo
    targets.  ``True`` iff *needle* appears in the file at
    ``repo_root / file_path``.  Missing file → ``False``.
    """
    target = repo_root / file_path
    if not target.is_file():
        return False
    try:
        return needle in target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Fuzzy suggestion
# ---------------------------------------------------------------------------


def fuzzy_suggest(symbol: str, candidates: list[str]) -> str | None:
    """Return the closest match to *symbol* from *candidates* or ``None``.

    Cutoff `0.6` — the `difflib` default — is loose enough to catch
    plausible typo/rename drift (``foo_bar`` → ``foo_baz``) without
    drowning operators in spurious suggestions.
    """
    matches = difflib.get_close_matches(symbol, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None
