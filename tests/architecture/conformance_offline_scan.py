"""Static machinery behind the offline-conformance rule (#11688, #11706).

The rule lives in ``docs/standards/vitals_conformance/README.md``; the policy
(which names count) lives in ``vitals_conformance_registry`` and in
``test_vitals_conformance_seam``. This module is the *mechanics* those two
share, and it exists because the first version of the check had two structural
holes that made it green by luck rather than by observation (#11706):

1. **It parsed one file.** ``_imported_roots(path)`` collected a single file's
   own top-level imports, so a conformance check that imported a local module
   which imported a remote client was invisible. :class:`ImportGraph` resolves
   first-party imports to files and walks them to a fixed point instead.

2. **``subprocess`` walked straight past it.** A check that shells out to
   ``curl``/``gh``/``aws`` satisfies an import sweep completely.
   :func:`spawn_sites` reads the argv of every spawn call instead.

Both are *static* proxies and neither is a proof. The proof that the
conformance suite runs offline is an egress-blocked CI lane, which the standard
names and this module does not replace.
"""

from __future__ import annotations

import ast
import re
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "LOCAL_HOST_RE",
    "URL_RE",
    "ImportGraph",
    "Reach",
    "SpawnSite",
    "remote_hosts",
    "spawn_sites",
]

# --------------------------------------------------------------------------
# Hosts
# --------------------------------------------------------------------------

#: Hosts that are not a remote service: loopback, and the TLDs RFC 2606
#: reserves precisely so a test can name a host it will never contact.
LOCAL_HOST_RE: Final = re.compile(
    r"^(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?$|"
    r"\.(?:test|invalid|example|localhost)$",
    re.IGNORECASE,
)

URL_RE: Final = re.compile(r"(?:https?|ftp|ftps|git|ssh|rsync)://([^/\s\"']+)")

#: ``git@github.com:owner/repo`` — scp-style, no scheme, still a network reach.
_SCP_RE: Final = re.compile(r"\b[\w.-]+@([\w.-]+\.[a-z]{2,}):", re.IGNORECASE)


def remote_hosts(text: str) -> list[str]:
    """Hosts in *text* that are neither loopback nor an RFC-2606 sentinel."""
    found = set(URL_RE.findall(text)) | set(_SCP_RE.findall(text))
    return sorted(h for h in found if not LOCAL_HOST_RE.search(h))


# --------------------------------------------------------------------------
# First-party import graph
# --------------------------------------------------------------------------


#: Callees whose first string argument REFERENCES a module rather than importing
#: one. ``logging.getLogger("botocore")`` quiets a noisy logger;
#: ``mock_import.assert_called_once_with("boto3")`` asserts about an import that
#: was MOCKED and therefore never happened.
#:
#: Yes, this is an enumeration, and the rule below exists because enumerating
#: was the wrong move. The difference is which side of the error it sits on. The
#: enumeration this rule escaped was on the DETECTION side, where a spelling
#: nobody thought of is a SILENT false negative: nothing reddens, the hole stays
#: open, and it is found only by going looking. An enumeration on the SAFE side
#: fails the other way — a callee nobody excluded is a LOUD false positive that
#: whoever wrote it hits immediately and fixes in one line. Unbounded silent
#: misses and bounded loud misses are not the same risk.
#:
#: The trigger is not hypothetical, which is why this is closed rather than
#: declared: ``_ANTHROPIC_MODEL_ID`` already accepts Bedrock ids, and the day a
#: ``boto3``-backed client lands in ``src`` the obvious regression test mocks
#: the lazy import and asserts it was called with ``"boto3"``. The import rule
#: has no waiver mechanism by design, so without this that author's only exits
#: are degrading the test or reopening a settled design decision mid-feature.
#:
#: ``assert*`` is a prefix rather than a list because every mock and unittest
#: assertion shares it. ``importorskip`` and ``patch`` are deliberately NOT
#: here: both really do import the module they name.
_REFERENCE_CALLEES: Final[frozenset[str]] = frozenset({"getLogger", "get_logger"})


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _references_without_importing(call: ast.Call) -> bool:
    name = _callee_name(call)
    return name.startswith("assert") or name in _REFERENCE_CALLEES


def _named_module_argument(call: ast.Call) -> str | None:
    """The module name a call's FIRST POSITIONAL argument names, if it is a literal.

    This rule resolves the ARGUMENT, not the CALLEE, and that inversion is the
    whole point.

    #11706's census found ``importlib`` sitting alongside ``subprocess`` in the
    conformance roots' escape hatches, and a sweep reading only
    ``ast.Import``/``ImportFrom`` treats a dynamic import as ordinary code. Two
    earlier versions of this function tried to recognise the *callee*: first by
    literal spelling (walked past by ``import_module as im``), then by resolving
    the file's own ``ImportFrom`` bindings (walked past by ``from importlib
    import *`` and by ``load = importlib.import_module``). Each fix was one more
    arm on an enumeration of binding forms, which is #11723's shape and the
    thing PR #11717 stopped doing after five spellings.

    So stop enumerating. The callee's identity is unbounded — aliases, star
    imports, rebinding, ``getattr``, cross-file re-export, wrappers like
    ``pytest.importorskip`` and ``mock.patch`` that import as a side effect. The
    ARGUMENT is a literal or it is not. A call that hands a remote client's
    module name to something is doing something with that client, whatever the
    something is called; the sweep intersects what comes back with
    ``_REMOTE_CLIENTS`` and nothing else, so every other string is inert.

    Measured across all 1471 files the conformance roots reach: zero calls take
    a remote-client name as their first positional argument. The one shape that
    looks like a hit and is not — the ``frozenset({...})`` literal that DEFINES
    the client set — is excluded because its first argument is a set, not a
    string.

    Inverting a rule is not free: it moves the error to the other side.
    ``_REFERENCE_CALLEES`` above is what keeps this inversion's false-positive
    surface bounded and, crucially, LOUD rather than silent.

    THE DECLARED LIMIT, which is not enumerable away and is recorded in the
    standard rather than patched around:

    - a module name that is not a first-positional string literal — computed at
      runtime, read from a variable, or passed by keyword. Same residual class
      as an argv assembled from non-literals.
    - a dynamically imported FIRST-PARTY module is not followed as a graph edge.
      195 first-positional literals in the corpus resolve to a local module and
      essentially all are ``monkeypatch.setattr("state.x", …)`` targets rather
      than imports; turning those into edges would put whole subtrees behind a
      coincidence, and the import rule has no waiver mechanism to undo a false
      positive. Static imports of those modules are followed as normal.

    The same limit already applies to ``_SpawnNames`` below, which resolves
    ``import subprocess as sp`` but not ``spawn = subprocess.run``.
    """
    if not call.args or _references_without_importing(call):
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


@dataclass(frozen=True, slots=True)
class Reach:
    """One file's shortest path to a name the caller asked about.

    ``chain`` starts at the swept file and ends at the module that does the
    importing, so the failure message can name the hop that carries it rather
    than only the file that is blamed.
    """

    chain: tuple[Path, ...]
    names: tuple[str, ...]

    via: str = "imports"
    """How the last hop reaches them — an import statement, or a module name
    handed to a call. Worth saying, because the fix differs."""

    def describe(self, root: Path) -> str:
        hops = " -> ".join(str(p.relative_to(root)) for p in self.chain)
        return f"{hops} {self.via} {list(self.names)}"


class ImportGraph:
    """First-party imports resolved to files and walked to a fixed point.

    *bases* are the roots a dotted module name resolves against, in order.
    For this repo that is ``src/`` then the repo root, mirroring what
    ``tests/conftest.py`` puts on ``sys.path``. A dotted name that resolves
    under one of them is **first-party** and the walk follows it; anything else
    is a leaf that contributes its top-level root.

    Cycles are real here (``src`` packages import each other), so the walk is a
    visited-set BFS rather than recursion: it terminates, and because it is
    breadth-first the reported chain is a shortest one.
    """

    def __init__(self, bases: Sequence[Path]) -> None:
        self._bases = tuple(bases)
        self._edges: dict[Path, tuple[frozenset[str], frozenset[Path]]] = {}
        self._named: dict[Path, frozenset[str]] = {}
        self._modules: dict[str, Path | None] = {}
        self._listings: dict[Path, frozenset[str]] = {}

    # -- resolution --------------------------------------------------------

    def _names_in(self, directory: Path) -> frozenset[str]:
        cached = self._listings.get(directory)
        if cached is None:
            try:
                cached = frozenset(child.name for child in directory.iterdir())
            except OSError:
                cached = frozenset()
            self._listings[directory] = cached
        return cached

    def _resolve_under(self, base: Path, parts: Sequence[str]) -> Path | None:
        """Resolve *parts* under *base*, matching case EXACTLY.

        ``Path.is_file()`` is case-insensitive on macOS and case-sensitive on
        the Linux runners, so ``from vendor import Client`` resolves
        ``vendor/client.py`` on a laptop and nothing in CI. That is a
        host-dependent import graph: the same tree yields different chains, and
        a guard whose answer depends on the developer's filesystem is not a
        guard. Directory listings are compared instead, and cached.
        """
        current = base
        for part in parts[:-1]:
            if part not in self._names_in(current):
                return None
            current = current / part
        last = parts[-1]
        names = self._names_in(current)
        module = current / f"{last}.py"
        if f"{last}.py" in names and module.is_file():
            return module
        package = current / last / "__init__.py"
        if last in names and package.is_file():
            return package
        return None

    def module_file(self, dotted: str) -> Path | None:
        """The file a dotted first-party module name names, or ``None``."""
        if dotted in self._modules:
            return self._modules[dotted]
        resolved: Path | None = None
        parts = dotted.split(".")
        if all(parts):
            for base in self._bases:
                resolved = self._resolve_under(base, parts)
                if resolved is not None:
                    break
        self._modules[dotted] = resolved
        return resolved

    def _package_of(self, path: Path) -> str:
        """Dotted package containing *path*, for resolving relative imports."""
        for base in self._bases:
            try:
                rel = path.relative_to(base)
            except ValueError:
                continue
            return ".".join(rel.parts[:-1])
        return ""

    def _absolute(self, node: ast.ImportFrom, path: Path) -> str:
        """``from . import x`` resolved against the importing file's package.

        Relative imports were dropped entirely by the pre-#11706 sweep. That is
        fine for a one-file parse — a relative import cannot name a third-party
        client — but fatal for a transitive one: every ``src`` package re-exports
        through ``__init__`` with ``from ._impl import ...``, so ignoring level
        > 0 stops the walk dead at the first package boundary.
        """
        if node.level == 0:
            return node.module or ""
        parts = self._package_of(path).split(".")
        parts = [p for p in parts if p]
        climb = node.level - 1
        if climb:
            parts = parts[: len(parts) - climb] if climb <= len(parts) else []
        if node.module:
            parts = [*parts, node.module]
        return ".".join(parts)

    # -- edges -------------------------------------------------------------

    def edges(self, path: Path) -> tuple[frozenset[str], frozenset[Path]]:
        """(third-party roots imported here, first-party files imported here)."""
        cached = self._edges.get(path)
        if cached is not None:
            return cached
        external: set[str] = set()
        local: set[Path] = set()
        named: set[str] = set()

        def consider(dotted: str) -> bool:
            """Follow *dotted*, or the longest prefix of it that resolves.

            The reachable trigger is a submodule this resolver cannot see as a
            file: a PEP 420 namespace package (a directory with no
            ``__init__.py``) or a compiled extension. ``import pkg.sub`` is then
            a perfectly valid import that resolves to no ``.py``, and without
            the fallback ``pkg`` is recorded as a third-party leaf — dropping
            the edge into ``pkg/__init__.py``, which is exactly where a package
            puts the import that carries the client.

            NOT the trigger, despite being the obvious guess: ``import
            pkg.Thing`` where ``Thing`` is a re-exported NAME. That raises at
            import time, so it cannot reach a sweep.
            """
            parts = dotted.split(".")
            while parts:
                resolved = self.module_file(".".join(parts))
                if resolved is not None:
                    local.add(resolved)
                    return True
                parts.pop()
            return False

        for node in ast.walk(self._parse(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not consider(alias.name):
                        external.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute(node, path)
                if not base:
                    continue
                resolved = consider(base)
                for alias in node.names:
                    # ``from pkg import mod`` — the name may be a submodule,
                    # and following it is the difference between reaching
                    # ``pkg/__init__.py`` and reaching the module that carries
                    # the client.
                    if alias.name != "*":
                        consider(f"{base}.{alias.name}")
                if not resolved and node.level == 0:
                    external.add(base.split(".")[0])
            elif isinstance(node, ast.Call):
                literal = _named_module_argument(node)
                if literal:
                    named.add(literal.split(".")[0])

        result = (frozenset(external), frozenset(local))
        self._edges[path] = result
        self._named[path] = frozenset(named)
        return result

    def named_roots(self, path: Path) -> frozenset[str]:
        """Top-level module names *path* hands to a call as a string literal.

        Kept out of :meth:`edges` deliberately: these are evidence about a
        NAME, not an edge in the graph. They are only ever intersected with the
        caller's target set, so an unrelated string literal is inert.
        """
        if path not in self._named:
            self.edges(path)
        return self._named[path]

    @staticmethod
    def _parse(path: Path) -> ast.Module:
        try:
            return ast.parse(path.read_text(errors="replace"), filename=str(path))
        except (SyntaxError, ValueError, OSError):  # pragma: no cover
            # A file that will not parse fails in its own suite; it must not
            # take the sweep down with it.
            return ast.Module(body=[], type_ignores=[])

    # -- walks -------------------------------------------------------------

    def find(self, start: Path, targets: Iterable[str]) -> Reach | None:
        """Shortest chain from *start* to a file importing one of *targets*."""
        wanted = frozenset(targets)
        if not wanted:
            return None
        chains: dict[Path, tuple[Path, ...]] = {start: (start,)}
        queue: deque[Path] = deque([start])
        while queue:
            current = queue.popleft()
            external, local = self.edges(current)
            hit = external & wanted
            if hit:
                return Reach(chain=chains[current], names=tuple(sorted(hit)))
            hit = self.named_roots(current) & wanted
            if hit:
                return Reach(
                    chain=chains[current],
                    names=tuple(sorted(hit)),
                    via="names as a module argument to a call —",
                )
            for nxt in local:
                if nxt not in chains:
                    chains[nxt] = (*chains[current], nxt)
                    queue.append(nxt)
        return None

    def reach(self, start: Path) -> tuple[frozenset[str], frozenset[Path]]:
        """Every third-party root and first-party file reachable from *start*."""
        external: set[str] = set()
        seen: set[Path] = {start}
        queue: deque[Path] = deque([start])
        while queue:
            current = queue.popleft()
            own_external, local = self.edges(current)
            external |= own_external
            for nxt in local:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        seen.discard(start)
        return frozenset(external), frozenset(seen)


# --------------------------------------------------------------------------
# Spawn sites
# --------------------------------------------------------------------------

#: Stdlib entry points that start a process. Keyed by the module they live on
#: so ``import subprocess as sp`` and ``from subprocess import run`` both
#: resolve without treating every ``run(...)`` in the repo as a spawn.
_STDLIB_SPAWNS: Final[dict[str, frozenset[str]]] = {
    "subprocess": frozenset(
        {
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
        }
    ),
    "os": frozenset(
        {
            "system",
            "popen",
            "execl",
            "execlp",
            "execv",
            "execve",
            "execvp",
            "execvpe",
            "spawnl",
            "spawnlp",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "posix_spawn",
            "posix_spawnp",
        }
    ),
    "asyncio": frozenset({"create_subprocess_exec", "create_subprocess_shell"}),
}

#: HydraFlow's own bounded-spawn seam. ``tests/architecture/
#: test_subprocess_reap_guard.py`` forbids raw spawns inside ``src`` precisely
#: so that everything goes through these, which means a sweep that watched only
#: the stdlib primitives would watch the one path production code may not use.
_WRAPPER_SPAWNS: Final[frozenset[str]] = frozenset(
    {
        "run_subprocess",
        "run_subprocess_result",
        "run_simple",
        "stream_claude_process",
    }
)

#: Shell metacharacters that start a new command inside a ``-c`` script.
_SHELL_SPLIT: Final = re.compile(r"[;&|\n()`]+")


@dataclass(frozen=True, slots=True)
class SpawnSite:
    """One call that starts a process, and what its argv literals say."""

    path: str
    """Repo-relative."""

    line: int
    call: str
    """Dotted callee, so the message can point at the shape, not just the line."""

    argv: tuple[str, ...]
    """Whitespace/shell-separator tokens of every string literal in the argv."""

    def binaries(self, network_binaries: Iterable[str]) -> tuple[str, ...]:
        """Network binaries named ANYWHERE in the argv, not only at position 0.

        Deliberately fail-closed. Restricting the match to "command position"
        would read better and would drop a hypothetical false positive (a
        commit message containing the word ``uv``), but it means enumerating
        every way a command can start — ``bash -c``, ``python -m``, ``sudo``,
        ``env``, ``xargs``, ``nohup``, a shell chain — and a position this code
        failed to anticipate is a reach it silently misses. A guard written
        against fail-open cannot be the one that fails open. Zero false
        positives across the ~165 real spawn sites; if one appears, it is a
        registered waiver, which is visible.

        The known false-positive shape, for whoever meets it first: a local path
        whose final component happens to equal a listed binary, e.g.
        ``git -C /tmp/x/docker status``, because ``_argv_tokens`` also emits
        basenames so ``/usr/bin/curl`` is ``curl``. Nothing collides across the
        current sites. Narrowing the basename to "command position" would fix it
        and open a hole for ``sudo /usr/bin/curl``, so the collision stays a
        waiver rather than a special case.
        """
        wanted = frozenset(network_binaries)
        return tuple(sorted({token for token in self.argv if token in wanted}))

    def hosts(self) -> tuple[str, ...]:
        return tuple(remote_hosts(" ".join(self.argv)))


def _dotted_call(func: ast.expr) -> tuple[str, ...] | None:
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


class _SpawnNames:
    """What the spawn primitives are called *in one file*."""

    def __init__(self, tree: ast.Module) -> None:
        self.aliases: dict[str, str] = {}
        self.bare: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in _STDLIB_SPAWNS:
                        self.aliases[alias.asname or alias.name] = root
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                funcs = _STDLIB_SPAWNS.get(root, frozenset())
                for alias in node.names:
                    if alias.name in funcs:
                        self.bare.add(alias.asname or alias.name)

    def is_spawn(self, func: ast.expr) -> bool:
        dotted = _dotted_call(func)
        if dotted is None:
            return False
        last = dotted[-1]
        if last in _WRAPPER_SPAWNS:
            return True
        if len(dotted) == 1:
            return last in self.bare
        owner = dotted[-2]
        module = self.aliases.get(owner, owner if owner in _STDLIB_SPAWNS else None)
        return module is not None and last in _STDLIB_SPAWNS[module]


#: Parameter names that carry argv. ``subprocess.run(args=[...])`` is ordinary,
#: working Python — ``run(*popenargs, **kwargs)`` forwards straight into
#: ``Popen(args=...)`` — and a scanner that reads only ``call.args`` sees a real
#: spawn with an EMPTY argv and reports nothing. ``cmd=`` is how
#: ``stream_claude_process`` takes it; ``program=`` is
#: ``create_subprocess_exec``'s.
_ARGV_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"args", "argv", "cmd", "command", "program", "executable"}
)


def _argv_nodes(call: ast.Call) -> list[ast.expr]:
    """Every argument node that can carry argv.

    ``subprocess.run(["git", ...])`` puts argv in one list; ``run_subprocess(
    "git", "status")`` and ``create_subprocess_exec("gh", "pr", ...)`` spread it
    across positionals. Reading only ``args[0]`` in the second shape sees the
    binary and misses the URL it is pointed at.

    Keywords are read in every shape, not only when the positionals are empty:
    ``Popen(["sh"], executable="/usr/bin/curl")`` puts the real binary in a
    keyword while the positional list looks innocent.
    """
    nodes: list[ast.expr] = []
    if call.args:
        first = call.args[0]
        nodes.extend([first] if isinstance(first, ast.List | ast.Tuple) else call.args)
    nodes.extend(
        keyword.value
        for keyword in call.keywords
        if keyword.arg in _ARGV_KEYWORDS and keyword.value is not None
    )
    return nodes


def _argv_tokens(call: ast.Call) -> tuple[str, ...]:
    tokens: list[str] = []
    for arg in _argv_nodes(call):
        for node in ast.walk(arg):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for chunk in _SHELL_SPLIT.split(node.value):
                    for token in chunk.split():
                        tokens.append(token)
                        # ``/usr/bin/curl`` is ``curl``. Matching whole tokens
                        # only would let an absolute path walk past the binary
                        # list — the same miss as a keyword argv, one character
                        # of punctuation further along.
                        if "/" in token:
                            tokens.append(token.rsplit("/", 1)[-1])
    return tuple(tokens)


def spawn_sites(path: Path, rel: str) -> list[SpawnSite]:
    """Every process-spawning call in *path*, with its argv literals.

    Only real ``ast.Call`` nodes count. Several conformance checks embed spawn
    source in a *string* to feed a scanner fixture — those are data, and a
    text-level grep would flag every one of them.
    """
    try:
        tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
    except (SyntaxError, ValueError, OSError):  # pragma: no cover
        return []
    names = _SpawnNames(tree)
    sites: list[SpawnSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not names.is_spawn(node.func):
            continue
        dotted = _dotted_call(node.func) or ()
        sites.append(
            SpawnSite(
                path=rel,
                line=node.lineno,
                call=".".join(dotted),
                argv=_argv_tokens(node),
            )
        )
    return sites
