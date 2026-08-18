---
id: 0401
topic: architecture
source_issue: 11413
source_phase: plan
created_at: 2026-08-18T03:10:14.007954+00:00
status: active
corroborations: 1
---

# Never add _QUIET_UNKNOWN_GH_SHAPES entries for FakeGitHub modelled paths

Do not add a `_QUIET_UNKNOWN_GH_SHAPES` allowlist entry for any path `FakeGitHub` is actively modelling — the allowlist converts a fail-loud raise into a silent `[]`.

- When adding `api repos/{repo}/git/matching-refs/heads/{prefix}` support, raise `FakeGitHubUnmodelledCommand` for unrecognized `--jq` on that path.
- The allowlist exists for genuinely unmodelled endpoints, not as a shortcut for partially-modelled ones.

**Why:** An allowlist entry on a modelled path re-hides the exact fidelity gap the fail-loud pattern was built to expose.
