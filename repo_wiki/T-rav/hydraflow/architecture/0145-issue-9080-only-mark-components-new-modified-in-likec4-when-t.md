---
id: 0145
topic: architecture
source_issue: 9080
source_phase: review
created_at: 2026-06-12T09:06:10.457698+00:00
status: active
corroborations: 1
---

# Only mark components #new/#modified in LikeC4 when the code exists in the same PR

Never add `#new` or `#modified` tags to a LikeC4 component that is planned but not yet implemented in the same commit set.

- Wrong: tagging `GitHubSandboxProvisioner` and `contract_github_recording_enabled` as `#new` before their source files exist.
- Right: add the tags in the same PR that introduces `src/contract_github_sandbox.py`.

**Why:** Diagram-before-implementation creates day-one documentation drift that arch-regen tools and reviewers flag as incorrect, poisoning the living-architecture signal.
