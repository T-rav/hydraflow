---
id: 3564
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.860506+00:00
status: superseded
corroborations: 1
supersedes: 3417
superseded_by: 3709
---

# gen-gates-check only byte-compares inside generated markers

Hand-written prose outside `<!-- generated:gates -->` markers in `docs/standards/branch_protection/README.md` is invisible to `make gen-gates-check` — `gen_gates._readme_with_block` splices only the span between markers, so stale claims there drift permanently undetected.

Example: A README can say "2 required checks" two lines below a generated table showing 3, and `gen-gates-check` stays green. Add `validate_prose_counts` in `scripts/gates/validate.py` wired into the `violations` list in `scripts/gen_gates.py:main()`.

**Why:** Without a dedicated prose-count predicate, the generated-block check creates a false green on exactly the sentences operators read first.
