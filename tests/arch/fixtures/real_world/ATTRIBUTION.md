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

## Go — hashicorp/go-multierror

- **Repo:** https://github.com/hashicorp/go-multierror
- **Commit SHA:** `6d4d48630db25c3c83fa83ecd41dd8438b82963c`
- **License:** MPL-2.0
- **Files vendored:** `multierror.go`, `append.go`, `flatten.go`, `format.go`,
  `prefix.go`, `sort.go`, `group.go`, `go.mod`, `LICENSE`
- **Extractor finding:** Go module unit is `directory`. All 7 `.go` files live in
  the repository root, so all resolve to the single node `"."`. All imports are
  standard-library (`errors`, `fmt`, `sort`) — none resolve to internal paths.
  Result: 1 node (`"."`), 0 edges. This is correct behaviour for a single-package
  library with no sub-packages and only external/stdlib imports. **Zero internal
  edges is expected** for this fixture.

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
