---
id: 0186
topic: architecture
source_issue: 10444
source_phase: plan
created_at: 2026-07-24T10:56:36.678061+00:00
status: stale
corroborations: 1
stale_reason: drift_detected: src/….py
---

# ADR `.py::Symbol` (double colon) citations silently drop from source_files

`adr_index._SOURCE_FILE_CITATION_RE` matches a backtick `src/….py:Symbol` cite with a single colon; `::` matches nothing, so the file never enters `source_files` and the ADR-drift gate never fires for it — a silent miss, not an error. Example: ADR-0049 lines 74-75 cited `src/base_background_loop.py::LoopDeps` and `src/bg_worker_manager.py::BGWorkerManager.is_enabled` with `::`, so drift coverage for both kill-switch modules was silently absent. Fix is a single-colon repoint; the lenient `arch-regen` xref extractor already indexed these correctly, so only the runtime gate was affected. **Why:** a malformed citation looks correct to a human reader but silently disables drift detection for that module — this is the second occurrence (first was #9514).
