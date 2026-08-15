---
id: 2651
topic: testing
source_issue: 11246
source_phase: plan
created_at: 2026-08-15T20:20:19.664592+00:00
status: active
corroborations: 1
---

# Parse gh issue number from args[2:], skipping flag values

When extracting an issue number from `gh issue <sub> <args>`, scan `args[2:]` for the first all-digits token but skip tokens that are values of preceding flags (e.g. `--repo owner/repo` where the repo slug may contain digits).

Mirror the existing `issue close` branch pattern in src/mockworld/fakes/fake_github.py. Test with `--repo owner/repo` to guard against the flag-value trap.

**Why:** Naive first-digits-token extraction picks up digits inside a repo slug and silently targets the wrong issue or misses the real one.
