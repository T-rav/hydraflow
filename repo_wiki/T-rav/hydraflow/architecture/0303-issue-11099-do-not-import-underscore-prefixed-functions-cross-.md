---
id: 0303
topic: architecture
source_issue: 11099
source_phase: plan
created_at: 2026-08-14T07:08:09.480537+00:00
status: active
corroborations: 1
---

# Do not import underscore-prefixed functions cross-module

Private helpers like `trace_collector._loop_trace_dir` must not be imported from other modules. Add a public wrapper in the owning module and import that instead.

- `src/trace_collector.py`: add `read_loop_traces(loop, limit)`
- Other modules import `read_loop_traces`, never `_loop_trace_dir`

**Why:** Underscore-prefixed functions are implementation details that can be refactored or removed without notice; cross-module imports create hidden coupling that breaks silently on refactor.
