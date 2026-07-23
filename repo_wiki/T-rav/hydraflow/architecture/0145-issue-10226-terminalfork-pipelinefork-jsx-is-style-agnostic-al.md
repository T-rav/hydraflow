---
id: 0145
topic: architecture
source_issue: 10226
source_phase: plan
created_at: 2026-07-22T04:13:06.288054+00:00
status: stale
corroborations: 1
stale_reason: source issue #10226 closed
---

# TerminalFork (PipelineFork.jsx) is style-agnostic; alignment lives in each caller's bundle

`TerminalFork` in `src/ui/src/components/PipelineFork.jsx` renders the NEEDS HUMAN / MERGED arms but owns no layout styling — each caller (`StreamView.jsx`'s `flowFork`, `Header.jsx`'s `pipelineFork`) supplies its own fork-container style object. When fixing a visual bug in one caller's fork rendering, don't patch `TerminalFork` itself; fix the caller's style bundle so the other caller can't regress. Both callers must be checked and fixed identically for the same symptom (e.g. issue #10226 touched both `flowFork` and `pipelineFork`).

**Why:** centralizing the fix in `TerminalFork` would couple StreamView and Header layout together, so a change validated for one could silently break the other.
