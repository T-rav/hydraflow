---
id: 0224
topic: architecture
source_issue: 10581
source_phase: plan
created_at: 2026-07-26T01:56:36.497434+00:00
status: active
corroborations: 1
---

# Module ref resolution order for prose citations: repo_root → src/ → unique basename

When resolving a loosely-cited module path (e.g. `escape/detect.py` in prose) to a real file, try `repo_root/<ref>`, then `repo_root/src/<ref>`, then a unique basename match under `src/`; if the basename is ambiguous (matches ≥2 files), drop the citation rather than guessing.

- `src/wiki_prose_citations.py` implements this for symbols like `metrics.dedupe_by_detection_ref()`.
- Symbols are validated against a whole-`src/` definition index (def/class/module-level assignment), so a relocated symbol still resolves silently.

**Why:** prevents false-positive drift reports from third-party module names or ambiguous basenames while still catching genuinely unimplemented symbols.
