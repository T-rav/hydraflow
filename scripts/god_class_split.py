#!/usr/bin/env python3
"""Mechanically split a god class into a mixin package, and prove the split verbatim.

The house recipe for a class over the mass threshold (``erosion.mass``, the
standing roster #11547) is: extract cohesive clusters of methods into mixin
modules inside a package, re-export the class from ``__init__`` so every
existing ``from x import Y`` keeps working, and leave exactly ONE class
identity so ``patch.object(Y, ...)`` still resolves.

Doing that by hand is a hundred-odd copy-paste operations per batch, and a
single mis-pasted body is a behaviour change wearing a refactor's clothes.
Batches 1-3 (#11628 / #11645 / #11658) each rebuilt the same throwaway
scaffolding; this is that scaffolding, kept.

Two subcommands:

``split`` reads a JSON spec, slices each named method / top-level member out of
the source file at its exact line span (decorators and the comment banner above
it included) and writes it, byte-for-byte, into its destination module. It also
generates the collaborator-seam block each mixin needs: attribute annotations
(safe unguarded) and — under ``if TYPE_CHECKING:`` — the signature of every
sibling method the module calls but does not define. That guard placement is
not cosmetic: a runtime ``...`` body is a real class attribute and wins the MRO
over a sibling mixin's real implementation (#11629).

``verify`` is the correctness bar. It re-parses the class as it exists NOW
(following the package, folding in every base defined under the package) and
compares an ``ast.dump`` of every method body against the same class at a git
revision. Equal dumps mean the bodies moved verbatim; the counts it prints
(missing / extra / changed / duplicate) are what a decomposition PR reports.

    python scripts/god_class_split.py split  --spec docs/.../split.json
    python scripts/god_class_split.py verify --spec docs/.../split.json --before origin/staging

The spec (see ``--print-schema``)::

    {
      "source":  "src/foo.py",              # the file being split
      "package": "src/foo",                 # the package it becomes
      "class":   "Foo",
      "core":    {"file": "_foo.py", "doc": "..."},
      "modules": [
        {"file": "_bar.py", "mixin": "FooBarMixin", "doc": "...",
         "methods": ["_a", "_b"]},
        {"file": "_common.py", "doc": "...", "members": ["CONST", "helper"]}
      ]
    }

Anything not named in a module stays in ``core``.
"""

from __future__ import annotations

import argparse
import ast
import copy
import io
import json
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_HEADER = "from __future__ import annotations"


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------


def _block_start(node: ast.stmt, comments: set[int]) -> int:
    """1-based first line of *node*'s source block: decorators and banner included.

    The comment banner above a method (``# ---- adjustments ----``) documents
    the cluster, so it travels with the cluster. Walk up over contiguous
    comment lines; stop at the first blank or code line. *comments* holds real
    comment TOKEN lines — see ``_comment_lines`` for why a text test is wrong.
    """
    start = min([node.lineno, *[d.lineno for d in getattr(node, "decorator_list", [])]])
    while start - 1 in comments:
        start -= 1
    return start


@dataclass(frozen=True)
class Span:
    """A 1-based inclusive line span of the source file."""

    name: str
    start: int
    end: int

    def text(self, lines: list[str]) -> str:
        return "\n".join(lines[self.start - 1 : self.end])


@dataclass
class Module:
    file: str
    doc: str
    mixin: str | None = None
    methods: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)


@dataclass
class Spec:
    source: Path
    package: Path
    cls: str
    core_file: str
    core_doc: str
    modules: list[Module]

    @classmethod
    def load(cls, path: Path) -> Spec:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            source=Path(raw["source"]),
            package=Path(raw["package"]),
            cls=raw["class"],
            core_file=raw["core"]["file"],
            core_doc=raw["core"]["doc"],
            modules=[
                Module(
                    file=m["file"],
                    doc=m["doc"],
                    mixin=m.get("mixin"),
                    methods=list(m.get("methods", ())),
                    members=list(m.get("members", ())),
                )
                for m in raw["modules"]
            ],
        )

    def mixin_bases(self) -> list[str]:
        return [m.mixin for m in self.modules if m.mixin]


def _comment_lines(text: str) -> set[int]:
    """1-based line numbers that are NOTHING BUT a comment.

    Two traps this exists to avoid, both of which silently delete real code:

    * ``line.lstrip().startswith("#")`` also matches a Markdown heading inside
      a triple-quoted prompt template (``## Issue #42``). Tokenizing is the
      only way to tell a comment from a string that looks like one.
    * a line with a TRAILING comment (``def f() -> None: ...  # provided by
      _x``) is code, not a banner. Counting it lets a run of such lines read
      as one banner block and be dropped whole.
    """
    out: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip():
                out.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        return set()
    return out


def _drop_orphan_banners(text: str) -> str:
    """Delete comment banners whose section moved to another module.

    A banner that is followed (past blank lines) by another banner or by end of
    file no longer introduces anything; the code it labelled is gone.
    """
    lines = text.split("\n")
    comments = _comment_lines(text)
    keep = [True] * len(lines)
    i = 0
    while i < len(lines):
        if (i + 1) not in comments:
            i += 1
            continue
        start = i
        while i < len(lines) and (i + 1) in comments:
            i += 1
        j = i
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or (j + 1) in comments:
            for k in range(start, j):
                keep[k] = False
    return "\n".join(line for line, k in zip(lines, keep, strict=True) if k)


def _class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise SystemExit(f"class {name} not found")


def _method_nodes(cls: ast.ClassDef) -> dict[str, ast.stmt]:
    return {
        n.name: n
        for n in cls.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _member_nodes(tree: ast.Module) -> dict[str, ast.stmt]:
    out: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def _import_block(tree: ast.Module, lines: list[str]) -> str:
    """The source file's whole import prologue, verbatim, for ruff to prune."""
    ends = [
        n.end_lineno or n.lineno
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom)
    ]
    type_checking = [
        n
        for n in tree.body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Name)
        and n.test.id == "TYPE_CHECKING"
    ]
    ends += [n.end_lineno or n.lineno for n in type_checking]
    if not ends:
        return ""
    first = min(
        n.lineno
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom | ast.If)
    )
    block = lines[first - 1 : max(ends)]
    # ``from __future__ import annotations`` is emitted separately as the
    # generated module's first statement; keeping the copy would duplicate it.
    return "\n".join(line for line in block if line.strip() != _HEADER)


def _logger_line(tree: ast.Module, lines: list[str]) -> str:
    """The source's module logger assignment, so every slice keeps logging."""
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "logger"
        ):
            return "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
    return ""


# ---------------------------------------------------------------------------
# Seam discovery
# ---------------------------------------------------------------------------


def _self_attrs(node: ast.AST) -> tuple[set[str], set[str]]:
    """Return (methods called as ``self.x(...)``, other ``self.x`` accesses)."""
    called: set[str] = set()
    read: set[str] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "self"
        ):
            called.add(sub.func.attr)
        elif (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "self"
        ):
            read.add(sub.attr)
    return called, read - called


def _signature_stub(node: ast.stmt, provider: str) -> str:
    """Render *node*'s signature as a TYPE_CHECKING-only ``...`` declaration."""
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    # ``staticmethod`` / ``classmethod`` / ``property`` change how the seam
    # BINDS at the call site, so the declaration has to carry them or the
    # type-checker reads ``self`` into the first real parameter.
    binding = [
        d
        for d in node.decorator_list
        if isinstance(d, ast.Name)
        and d.id in {"staticmethod", "classmethod", "property"}
    ]
    clone = copy.deepcopy(node)
    clone.body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
    clone.decorator_list = list(binding)
    ast.fix_missing_locations(clone)
    text = ast.unparse(clone)
    text = text.replace("\n    ...", " ...").rstrip()
    return f"{text}  # provided by {provider}"


def _init_attr_types(cls: ast.ClassDef) -> dict[str, str]:
    """Map ``self._x`` to a type string, inferred from ``__init__``'s annotations."""
    init = _method_nodes(cls).get("__init__")
    if init is None or not isinstance(init, ast.FunctionDef | ast.AsyncFunctionDef):
        return {}
    params = {
        a.arg: ast.unparse(a.annotation)
        for a in [*init.args.args, *init.args.kwonlyargs]
        if a.annotation is not None
    }
    out: dict[str, str] = {}
    for stmt in ast.walk(init):
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            continue
        value = stmt.value
        if isinstance(value, ast.Name) and value.id in params:
            out[target.attr] = params[value.id]
    return out


_SEAM_BANNER = """    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``{cls}.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------"""


def _seam_block(
    *,
    cls_name: str,
    owned: set[str],
    used_methods: set[str],
    used_attrs: set[str],
    all_methods: dict[str, ast.stmt],
    provider_of: dict[str, str],
    attr_types: dict[str, str],
) -> str:
    # A ``@property`` reads as an attribute at the call site but is a method
    # on the class, so it belongs in the TYPE_CHECKING block with the rest —
    # annotating it as a plain attribute would drop the descriptor.
    foreign_methods = sorted(
        n for n in (used_methods | used_attrs) - owned if n in all_methods
    )
    foreign_attrs = sorted(n for n in used_attrs - owned if n not in all_methods)
    if not foreign_methods and not foreign_attrs:
        return ""
    out = [_SEAM_BANNER.format(cls=cls_name)]
    for name in foreign_attrs:
        out.append(f"    {name}: {attr_types.get(name, 'object  # TODO-SEAM type')}")
    if foreign_methods:
        out.append("")
        out.append("    if TYPE_CHECKING:")
        for name in foreign_methods:
            out.append("")
            stub = _signature_stub(all_methods[name], provider_of.get(name, "core"))
            out.extend(f"        {line}" for line in stub.splitlines())
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


def _rewrite_class_header(
    comments: set[int], cls: ast.ClassDef, bases: Iterable[str]
) -> tuple[int, int, str]:
    """Return (start, end, replacement) for the class header line(s)."""
    original = [ast.unparse(b) for b in cls.bases]
    ordered = [*sorted(bases), *original]
    header = f"class {cls.name}(\n"
    header += "".join(f"    {b},\n" for b in ordered)
    header += "):"
    first = cls.body[0].lineno
    start = min([cls.lineno, *[d.lineno for d in cls.decorator_list]])
    # The header ends on the line before the first body statement's block start.
    end = _block_start(cls.body[0], comments) - 1
    end = max(end, start)
    del first
    return start, end, header


def do_split(spec: Spec) -> int:
    source = spec.source
    text = source.read_text(encoding="utf-8")
    lines = text.split("\n")
    tree = ast.parse(text)
    cls = _class_node(tree, spec.cls)
    methods = _method_nodes(cls)
    members = _member_nodes(tree)
    comments = _comment_lines(text)
    imports = _import_block(tree, lines)
    logger_line = _logger_line(tree, lines)
    attr_types = _init_attr_types(cls)

    provider_of: dict[str, str] = {}
    for mod in spec.modules:
        for name in mod.methods:
            provider_of[name] = Path(mod.file).stem
    for name in methods:
        provider_of.setdefault(name, Path(spec.core_file).stem)

    spans: dict[str, Span] = {}
    for mod in spec.modules:
        for name in mod.methods:
            if name not in methods:
                raise SystemExit(f"{spec.cls} has no method {name!r}")
            node = methods[name]
            spans[f"m:{name}"] = Span(
                name, _block_start(node, comments), node.end_lineno or node.lineno
            )
        for name in mod.members:
            if name not in members:
                raise SystemExit(f"{source} has no top-level {name!r}")
            node = members[name]
            spans[f"t:{name}"] = Span(
                name, _block_start(node, comments), node.end_lineno or node.lineno
            )

    spec.package.mkdir(parents=True, exist_ok=True)

    # --- mixin / member modules -------------------------------------------
    for mod in spec.modules:
        body: list[str] = []
        owned = set(mod.methods)
        used_m: set[str] = set()
        used_a: set[str] = set()
        for name in mod.methods:
            called, read = _self_attrs(methods[name])
            used_m |= called
            used_a |= read
        chunks = [spans[f"t:{n}"].text(lines) for n in mod.members]
        method_chunks = [spans[f"m:{n}"].text(lines) for n in mod.methods]

        out = [f'"""{mod.doc}\n"""', "", _HEADER, ""]
        if imports:
            out += [imports, ""]
        if logger_line:
            out += ["", logger_line, ""]
        if chunks:
            out += ["", "\n\n".join(c.rstrip() for c in chunks), ""]
        if mod.mixin:
            out += [
                "",
                f"class {mod.mixin}:",
                f'    """{mod.doc.splitlines()[0]}"""',
                "",
            ]
            seam = _seam_block(
                cls_name=spec.cls,
                owned=owned,
                used_methods=used_m,
                used_attrs=used_a,
                all_methods=methods,
                provider_of=provider_of,
                attr_types=attr_types,
            )
            if seam:
                out += [seam]
            out += ["\n\n".join(c.rstrip() for c in method_chunks)]
        body = list(out)
        dest = spec.package / mod.file
        dest.write_text(
            _drop_orphan_banners("\n".join(body)).rstrip() + "\n", encoding="utf-8"
        )
        print(f"  wrote {dest} ({len(body)} chunks)")

    # --- core module -------------------------------------------------------
    drop: set[int] = set()
    for span in spans.values():
        drop.update(range(span.start, span.end + 1))
    hstart, hend, header = _rewrite_class_header(comments, cls, spec.mixin_bases())
    kept: list[str] = []
    for i, line in enumerate(lines, start=1):
        if i in drop:
            continue
        if i == hstart:
            kept.append(header)
            continue
        if hstart < i <= hend:
            continue
        kept.append(line)
    core = spec.package / spec.core_file
    core.write_text(
        _drop_orphan_banners("\n".join(kept)).rstrip() + "\n", encoding="utf-8"
    )
    print(f"  wrote {core}")
    source.unlink()
    print(f"  removed {source}")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _iter_py(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
    else:
        yield from sorted(root.rglob("*.py"))


def _collect_methods(paths: Iterable[Path], cls_name: str) -> dict[str, list[str]]:
    """Map method name -> [ast.dump of each definition] across *paths*.

    Every class in the scanned tree contributes: the host class and each mixin
    it inherits. A name appearing twice is a duplicate runtime definition —
    exactly the MRO hazard the split must not introduce.
    """
    found: dict[str, list[str]] = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != cls_name and not node.name.endswith("Mixin"):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.setdefault(stmt.name, []).append(ast.dump(stmt))
    return found


def _top_level_dumps(tree: ast.Module) -> dict[str, str]:
    """Map every module-level member name to its ``ast.dump``.

    The class is only half of a split: constants, dataclasses and free
    functions move too, and a slicing bug there is just as silent.
    """
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = ast.dump(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = ast.dump(node)
    return out


def _git_show(rev: str, path: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "show", f"{rev}:{path}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def do_verify(spec: Spec, before_rev: str) -> int:
    before_src = _git_show(before_rev, spec.source.as_posix())
    tree = ast.parse(before_src)
    cls = _class_node(tree, spec.cls)
    before = {
        n.name: ast.dump(n)
        for n in cls.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    after_all = _collect_methods(_iter_py(spec.package), spec.cls)
    after = {k: v[0] for k, v in after_all.items()}

    # The host class is expected to differ — new bases, a shorter body. Its
    # methods are covered above; everything ELSE at module level must be
    # byte-for-byte the same node.
    before_top = _top_level_dumps(tree)
    before_top.pop(spec.cls, None)
    after_top: dict[str, str] = {}
    for path in _iter_py(spec.package):
        if path.name == "__init__.py":
            continue
        after_top.update(_top_level_dumps(ast.parse(path.read_text(encoding="utf-8"))))
    after_top.pop(spec.cls, None)

    missing = sorted(set(before) - set(after))
    extra = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    duplicate = sorted(k for k, v in after_all.items() if len(v) > 1)

    print(f"{spec.cls}: {len(before)} methods at {before_rev} -> {len(after)} now")
    print(f"  missing   : {len(missing)} {missing or ''}")
    print(f"  extra     : {len(extra)} {extra or ''}")
    print(f"  changed   : {len(changed)} {changed or ''}")
    print(f"  duplicate : {len(duplicate)} {duplicate or ''}")

    top_missing = sorted(set(before_top) - set(after_top))
    top_changed = sorted(
        k for k in set(before_top) & set(after_top) if before_top[k] != after_top[k]
    )
    print(
        f"  top-level : {len(before_top)} members, "
        f"{len(top_missing)} missing {top_missing or ''}, "
        f"{len(top_changed)} changed {top_changed or ''}"
    )
    ok = not (missing or extra or changed or duplicate or top_missing or top_changed)
    print("  RESULT    : " + ("VERBATIM" if ok else "MISMATCH"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("split", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--spec", type=Path, required=True)
        if name == "verify":
            p.add_argument(
                "--before", required=True, help="git revision to compare against"
            )
    args = ap.parse_args(argv)
    spec = Spec.load(args.spec)
    if args.cmd == "split":
        return do_split(spec)
    return do_verify(spec, args.before)


if __name__ == "__main__":
    sys.exit(main())
