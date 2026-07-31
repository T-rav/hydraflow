---
id: 0284
topic: architecture
source_issue: 10867
source_phase: review
created_at: 2026-07-31T10:45:43.194306+00:00
status: active
corroborations: 1
---

# LikeC4 element IDs must be unique across all .likec4 files in a directory

Use globally unique top-level element identifiers in every `.likec4` file under `docs/architecture/`. LikeC4 composes all files in a directory into a single model, so `adrCorpus` declared independently in two files produces a duplicate-id collision. Example: renaming to `adr0027Corpus` in the ADR-0027 diagram avoided a collision with an element in `adr_drift_nudge.likec4`.

**Why:** Duplicate ids cause composition errors in `likec4 build` / the VS Code extension that span unrelated diagrams, invisible when reviewing either file in isolation.
