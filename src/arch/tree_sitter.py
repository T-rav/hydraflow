from __future__ import annotations

import ctypes
import pathlib
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import tree_sitter as _ts  # type: ignore[import-untyped]
import tree_sitter_languages  # type: ignore[import-untyped]

from arch.models import ImportGraph, ModuleUnit

# tree_sitter ships runtime classes but no py.typed marker; on some pyright
# configurations Language/Parser/Query/QueryCursor resolve as modules rather
# than classes. Aliasing through Any erases the bogus type so annotations and
# call sites don't trip pyright, while preserving runtime behaviour.
Language: Any = _ts.Language
Parser: Any = _ts.Parser
Query: Any = _ts.Query
QueryCursor: Any = _ts.QueryCursor

# tree_sitter_languages 1.10.2 ships a bundled .so; load it directly so we can
# call the C-level tree_sitter_<lang>() functions.  This avoids the broken
# tree_sitter_languages.get_language() / get_parser() shim which was compiled
# for tree-sitter <0.22 and fails with tree-sitter 0.25's new Language.__init__.
_TSL_SO = next(pathlib.Path(next(iter(tree_sitter_languages.__path__))).glob("*.so"))
_TSL_LIB = ctypes.cdll.LoadLibrary(str(_TSL_SO))


# Some languages are exposed by tree_sitter_languages under a symbol name that
# doesn't match the user-facing language key (e.g., C# ships as `c_sharp`).
_SYMBOL_OVERRIDES: dict[str, str] = {
    "csharp": "c_sharp",
}


def _load_language(name: str) -> Any:
    """Return a tree_sitter.Language for *name* using the bundled .so."""
    symbol = _SYMBOL_OVERRIDES.get(name, name)
    fn = getattr(_TSL_LIB, f"tree_sitter_{symbol}", None)
    if fn is None:
        raise ValueError(f"unsupported language {name!r}: symbol not found in .so")
    fn.restype = ctypes.c_void_p
    ptr = fn()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return Language(ptr)


SUPPORTED: dict[str, dict[str, Any]] = {
    "python": {
        "ext": (".py",),
        "unit": "file",
        # Capture the module name of `import X` / `from X import ...`. For
        # relative imports (from .foo import bar) module_name is a
        # relative_import node whose text is ".foo"; for absolute it's a
        # dotted_name like "foo.bar". `_resolve_relative` handles both.
        "query": (
            "(import_statement name: (dotted_name) @src) "
            "(import_from_statement module_name: _ @src)"
        ),
        "capture": "src",
    },
    "typescript": {
        "ext": (".ts", ".tsx"),
        "unit": "file",
        "query": "(import_statement source: (string) @src)",
        "capture": "src",
    },
    "javascript": {
        "ext": (".js", ".jsx", ".mjs"),
        "unit": "file",
        "query": "(import_statement source: (string) @src)",
        "capture": "src",
    },
    "go": {
        "ext": (".go",),
        "unit": "directory",
        "query": "(import_declaration (import_spec path: (interpreted_string_literal) @src))",
        "capture": "src",
    },
    "java": {
        "ext": (".java",),
        "unit": "file",
        "query": "(import_declaration (scoped_identifier) @src)",
        "capture": "src",
    },
    "rust": {
        "ext": (".rs",),
        "unit": "file",
        # `mod foo;` expresses a crate-internal module relation (foo.rs or
        # foo/mod.rs). `use foo::bar::Baz;` references a path; the argument
        # text is "foo::bar::Baz" and we fall back to the last segment as a
        # stem match.
        "query": (
            "(use_declaration argument: (_) @src) (mod_item name: (identifier) @src)"
        ),
        "capture": "src",
    },
    "ruby": {
        "ext": (".rb",),
        "unit": "file",
        "query": '(call method: (identifier) @m (#match? @m "require|require_relative") arguments: (argument_list (string) @src))',
        "capture": "src",
    },
    "csharp": {
        "ext": (".cs",),
        "unit": "file",
        "query": "(using_directive (qualified_name) @src)",
        "capture": "src",
    },
    "kotlin": {
        "ext": (".kt", ".kts"),
        "unit": "file",
        "query": "(import_header (identifier) @src)",
        "capture": "src",
    },
    "php": {
        "ext": (".php",),
        "unit": "file",
        "query": "(namespace_use_declaration (namespace_use_clause (qualified_name) @src))",
        "capture": "src",
    },
}

SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".git",
    "dist",
    "build",
    "vendor",
    "target",
}


def tree_sitter_extractor(language: str) -> Callable[[str], ImportGraph]:
    if language not in SUPPORTED:
        raise ValueError(
            f"unsupported language {language!r}; available: {sorted(SUPPORTED)}"
        )

    cfg = SUPPORTED[language]
    lang = _load_language(language)
    parser = Parser(lang)
    query = Query(lang, cfg["query"])
    cap_name: str | None = cfg["capture"]
    exts: tuple[str, ...] = cfg["ext"]
    unit: ModuleUnit = cast(ModuleUnit, cfg["unit"])

    def extract(repo_path: str) -> ImportGraph:
        root = Path(repo_path)
        graph = ImportGraph(module_unit=unit)

        files: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in exts:
                files.append(path)

        stems: dict[str, str] = {}
        for f in files:
            rel = f.relative_to(root).as_posix()
            graph.nodes.add(
                rel if unit == "file" else f.parent.relative_to(root).as_posix()
            )
            stems.setdefault(f.stem, rel)
            # Directory-unit languages (Go) resolve imports by last path
            # segment, which usually matches a package-directory basename
            # rather than a file stem. Populate those keys too; after the
            # lookup, `target` still points at a file inside the package
            # and `.parent` yields the directory node we want.
            if unit == "directory":
                stems.setdefault(f.parent.name, rel)

        for f in files:
            src_bytes = f.read_bytes()
            tree = parser.parse(src_bytes)
            rel_src = f.relative_to(root).as_posix()
            source_node = (
                rel_src if unit == "file" else f.parent.relative_to(root).as_posix()
            )
            cursor = QueryCursor(query)
            for _, captures in cursor.matches(tree.root_node):
                key = cap_name if cap_name is not None else next(iter(captures), None)
                if key is None:
                    continue
                nodes = captures.get(key, [])
                for node in nodes:
                    text = src_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="ignore"
                    )
                    spec = _strip_quotes(text)
                    target = _resolve_relative(
                        f.parent, spec, exts, root, language
                    ) or stems.get(_stem_key(spec, language))
                    if target is None:
                        continue
                    resolved = target if unit == "file" else str(Path(target).parent)
                    if resolved != source_node:
                        graph.add_edge(source_node, resolved)
        return graph

    return extract


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] in "\"'":
        return s[1:-1]
    return s


def _resolve_relative(
    base: Path, spec: str, exts: tuple[str, ...], root: Path, language: str
) -> str | None:
    """Resolve a relative import spec to a repo-relative file path.

    Two relative-import styles are handled:

    * ES-module style (``./foo``, ``../bar``) used by TS/JS and Ruby
      ``require_relative``.
    * Python style (``.foo``, ``..foo.bar``, bare ``.``) where leading dots
      express package level rather than path segments.
    """
    if not spec:
        return None
    if spec.startswith("./") or spec.startswith("../"):
        return _resolve_es_relative(base, spec, exts, root)
    if language == "python" and spec.startswith("."):
        return _resolve_python_relative(base, spec, exts, root)
    return None


def _resolve_es_relative(
    base: Path, spec: str, exts: tuple[str, ...], root: Path
) -> str | None:
    candidate = (base / spec).resolve()
    for ext in exts:
        p = candidate.with_suffix(ext)
        if p.is_file():
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return None
    for ext in exts:
        p = candidate / f"index{ext}"
        if p.is_file():
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return None
    return None


def _resolve_python_relative(
    base: Path, spec: str, exts: tuple[str, ...], root: Path
) -> str | None:
    """Resolve a Python relative import like ``.foo`` or ``..foo.bar``.

    Leading dots express package level: one dot = current package, two = parent,
    and so on. The first dotted segment after the dots is the target module.
    """
    dots = 0
    while dots < len(spec) and spec[dots] == ".":
        dots += 1
    remainder = spec[dots:]
    if not remainder:
        return None  # bare "from . import X" — we have no X to resolve
    target_dir = base
    for _ in range(dots - 1):
        target_dir = target_dir.parent
    first_segment = remainder.split(".")[0]
    for ext in exts:
        p = target_dir / (first_segment + ext)
        if p.is_file():
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return None
    pkg_dir = target_dir / first_segment
    if pkg_dir.is_dir():
        for ext in exts:
            init = pkg_dir / f"__init__{ext}"
            if init.is_file():
                try:
                    return init.relative_to(root).as_posix()
                except ValueError:
                    return None
    return None


def _stem_key(spec: str, language: str) -> str:
    """Derive the basename stem used as a fallback key in the ``stems`` map.

    Languages differ in how a module path is separated:

    * ``/`` for ES-module and Go imports (``./foo/bar`` → ``bar``).
    * ``.`` for Java / Kotlin / C# scoped identifiers
      (``com.example.Bar`` → ``Bar``).
    * ``::`` for Rust paths (``core::hint`` → ``hint``).
    * ``\\`` for PHP namespaces (``App\\Models\\User`` → ``User``).
    """
    if language in ("java", "kotlin", "csharp"):
        return spec.rsplit(".", 1)[-1]
    if language == "rust":
        return spec.rsplit("::", 1)[-1]
    if language == "php":
        return spec.rsplit("\\", 1)[-1]
    return spec.split("/")[-1].split(".")[0]
