# Real-World Extractor Fixture Attribution

These fixtures are small vendored snapshots of real open-source repositories, used
to integration-test the `tree_sitter_extractor` against non-trivial code.

Each language snapshot is ≤ 20 files and ≤ 50 KB total. The LICENSE file of the
upstream project is vendored alongside the source files.

---

## Python — theskumar/python-dotenv

- **Repo:** https://github.com/theskumar/python-dotenv
- **Commit SHA:** `bca6644d9aedbe287b792b756b3ae3d650cd0d3a`
- **License:** MIT
- **Files vendored:** `src/dotenv/__init__.py`, `src/dotenv/main.py`,
  `src/dotenv/parser.py`, `src/dotenv/variables.py`, `LICENSE`
- **Extractor finding:** Works correctly for relative imports. The query
  captures the `module_name` child of `import_from_statement`, and the
  Python-specific branch of `_resolve_relative` handles leading-dot package
  levels (`.main` → sibling `main.py`). 4 nodes, 3 internal edges.

---

## TypeScript — supermacro/neverthrow

- **Repo:** https://github.com/supermacro/neverthrow
- **Commit SHA:** `5ef3a018bda74fb960e44b68fc3672635ee8037d`
- **License:** MIT
- **Files vendored:** `src/index.ts`, `src/result.ts`, `src/result-async.ts`,
  `src/_internals/error.ts`, `src/_internals/utils.ts`, `LICENSE`
- **Extractor finding:** Works correctly. 5 nodes, 7 edges. Relative imports like
  `import { ... } from './result'` resolve properly. No false edges observed.

---

## JavaScript — sindresorhus/execa (lib/arguments subset)

- **Repo:** https://github.com/sindresorhus/execa
- **Commit SHA:** `f3a2e8481a1e9138de3895827895c834078b9456`
- **License:** MIT
- **Files vendored:** `lib/arguments/command.js`, `lib/arguments/cwd.js`,
  `lib/arguments/encoding-option.js`, `lib/arguments/escape.js`,
  `lib/arguments/fd-options.js`, `lib/arguments/file-url.js`,
  `lib/arguments/options.js`, `lib/arguments/shell.js`,
  `lib/arguments/specific.js`, `LICENSE`
- **Note:** Only the `lib/arguments/` subdirectory was vendored (9 files). The
  full execa repo has 50+ files; this subset was chosen because the files
  cross-import each other using ESM `import` statements with relative paths.
- **Extractor finding:** Works correctly for ESM `import` syntax. 9 nodes, 8
  edges. **CJS `require()` calls are NOT captured** — the extractor only handles
  ESM `import_statement` nodes. Libraries using CommonJS will produce zero edges.

---

## Go — synthesized two-package example (inspired by golang/groupcache)

- **Repo:** N/A — synthesized
- **License:** Apache-2.0 (fixture-local; matches golang/groupcache license)
- **Inspiration:** `golang/groupcache` (https://github.com/golang/groupcache,
  Apache-2.0), which has a separate `lru/` sub-package imported by the root
  `groupcache` package. The fixture mimics that two-package structure but is
  not a copy of any upstream file.
- **Files vendored:** `lru/lru.go`, `cache/cache.go`, `go.mod`, `LICENSE`
- **Why replaced:** The previous fixture (`hashicorp/go-multierror`) was a
  single-package repo where all files collapse to the `"."` directory node
  with stdlib-only imports, producing zero internal edges. The new fixture
  has two packages (`lru/` and `cache/`) where `cache` imports `lru` via a
  single-line `import "github.com/example/groupcache/lru"` statement.
- **Extractor finding:** 2 directory nodes (`lru`, `cache`), 1 cross-package
  edge `(cache, lru)`. The `stems` map is populated with `f.parent.name` for
  directory-unit languages; `"lru"` maps to `lru/lru.go`, so the import's last
  path segment resolves correctly. **Known limitation:** The tree-sitter query
  `(import_declaration (import_spec path: ...))` does NOT match grouped
  `import (...)` blocks — only single-line `import "pkg"` statements. The
  fixture uses single-line imports exclusively to work around this.

---

## Java — synthesized

- **Repo:** N/A — synthesized
- **License:** MIT (fixture-local)
- **Inspiration:** Functional-result-type pattern common in Java libraries (e.g.,
  `vavr-io/vavr`). Not copied from any upstream file.
- **Files vendored:** `src/main/java/com/example/result/Result.java`,
  `src/main/java/com/example/result/Success.java`,
  `src/main/java/com/example/result/Failure.java`, `LICENSE`
- **Why synthesized:** No suitably-tiny MIT/Apache Java library with 3–5 files and
  clear cross-file imports was found. `vavr`, `Optional`, and similar projects all
  exceed 20 files or have complex build setups. A synthesized 3-class example gives
  reproducible, license-clean coverage.
- **Extractor finding:** Works correctly. The language-specific stem key uses
  `spec.rsplit(".", 1)[-1]` for Java, extracting the class name (e.g., `Success`)
  from the scoped identifier `com.example.result.Success`, which matches the
  `Success.java` stem. 3 nodes, 2 internal edges.

---

## Rust — dtolnay/itoa

- **Repo:** https://github.com/dtolnay/itoa
- **Commit SHA:** `af77385d0daf4d0e949e81f2588be2e44f69f086`
- **License:** MIT and Apache-2.0 (dual-licensed); MIT file vendored
- **Files vendored:** `src/lib.rs`, `src/u128_ext.rs`, `Cargo.toml`, `LICENSE`
- **Extractor finding:** Works correctly for `mod foo;` crate-internal module
  declarations. The query now captures both `use_declaration` argument nodes and
  `mod_item` name identifiers; the stem key for Rust uses `rsplit("::", 1)[-1]`
  so that path-style uses (`core::hint`) and bare mod names (`u128_ext`) both
  resolve to the last segment. 2 nodes, 1 internal edge (`lib.rs` → `u128_ext.rs`
  via `mod u128_ext;`). External-crate `use` paths like `core::hint` correctly
  produce no edges because there's no matching file stem in the repo.

---

## Ruby — ruby/rake (lib subset)

- **Repo:** https://github.com/ruby/rake
- **Commit SHA:** `d9f85ffd9412df0175ec66ba28d682b40c8f3914`
- **License:** MIT
- **Files vendored:** `lib/rake.rb`, `lib/rake/version.rb`, `lib/rake/task.rb`,
  `lib/rake/invocation_exception_mixin.rb`, `lib/rake/dsl_definition.rb`,
  `lib/rake/file_utils_ext.rb`, `LICENSE`
- **Note:** Only `lib/rake.rb` plus 5 small sibling files from `lib/rake/` were
  vendored. The full rake `lib/` has 40+ files; this subset preserves a connected
  subgraph of `require_relative` edges.
- **Extractor finding:** Works correctly for `require_relative` calls. 6 nodes,
  6 edges. Stem-based resolution (e.g., `require_relative "rake/version"` → stem
  `"version"` → `lib/rake/version.rb`) works when only one file has that stem.
  No false edges observed.

---

## C# — synthesized 4-class result-type example

- **Repo:** N/A — synthesized
- **License:** MIT (fixture-local)
- **Inspiration:** Functional result-type pattern common in .NET libraries (e.g.,
  `ardalis/Result`, `altmann/FluentResults`). Not copied from any upstream file.
- **Files vendored:** `src/Result/IResult.cs`, `src/Result/Success.cs`,
  `src/Result/Failure.cs`, `src/Result/ResultFactory.cs`, `LICENSE`
- **Why synthesized:** Tiny MIT/Apache C# libraries with 3–5 files and clear
  inter-file `using` dependencies are rare; most real projects use namespace-level
  `using` that does not resolve to individual file stems. A synthesized example
  uses `using Example.Result.Success;` (class name as last segment) so the
  extractor's stem key `rsplit(".", 1)[-1]` = `"Success"` matches `Success.cs`.
- **Extractor finding:** Works correctly. The query `(using_directive
  (qualified_name) @src)` captures the full qualified name; stem extraction yields
  the class name which matches the corresponding `.cs` file. 4 nodes, 5 internal
  edges. `using Example.Result.IResult;` in both `Success.cs` and `Failure.cs`
  resolves to `IResult.cs`; `ResultFactory.cs` has edges to all three peers.

---

## Kotlin — synthesized 4-class result-type example

- **Repo:** N/A — synthesized
- **License:** MIT (fixture-local)
- **Inspiration:** Functional result-type pattern common in Kotlin (e.g.,
  `michaelbull/kotlin-result`, Apache-2.0). Not copied from any upstream file.
- **Files vendored:**
  `src/main/kotlin/com/example/result/IResult.kt`,
  `src/main/kotlin/com/example/result/Success.kt`,
  `src/main/kotlin/com/example/result/Failure.kt`,
  `src/main/kotlin/com/example/result/ResultFactory.kt`, `LICENSE`
- **Why synthesized:** Small Kotlin libraries with explicit same-package `import`
  statements between files are uncommon (same-package symbols are auto-available),
  but including `import com.example.result.Success` in companion files is valid
  and exercises the extractor's stem lookup. The fixture explicitly imports each
  class to produce measurable edges.
- **Extractor finding:** Works correctly. The query `(import_header (identifier)
  @src)` captures the full dotted path; `rsplit(".", 1)[-1]` extracts the class
  name which matches the `.kt` file stem. 4 nodes, 5 internal edges.

---

## PHP — synthesized 4-class result-type example

- **Repo:** N/A — synthesized
- **License:** MIT (fixture-local)
- **Inspiration:** PSR-style result-type pattern common in PHP libraries (e.g.,
  `league/result-type`, MIT). Not copied from any upstream file.
- **Files vendored:** `src/Result/IResult.php`, `src/Result/Success.php`,
  `src/Result/Failure.php`, `src/Result/ResultFactory.php`, `LICENSE`
- **Why synthesized:** Most real PHP libraries either use autoloading without
  explicit `use` statements, or are too large. A synthesized example provides
  clean `use Example\Result\Success;` statements whose backslash-separated last
  segment matches the `.php` file stem.
- **Extractor finding:** Works correctly. The query captures `qualified_name`
  inside `namespace_use_clause`; `rsplit("\\\\", 1)[-1]` extracts the class name.
  Bare class names like `use DateTime;` produce a `name` node (not
  `qualified_name`) and are correctly not captured, avoiding false external edges.
  4 nodes, 5 internal edges.
