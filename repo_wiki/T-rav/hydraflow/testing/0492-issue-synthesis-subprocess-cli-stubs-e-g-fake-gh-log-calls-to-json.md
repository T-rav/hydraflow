---
id: 0492
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:16:53.878960+00:00
status: active
corroborations: 1
supersedes: 0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491
---

# Subprocess CLI stubs (e.g. fake gh) log calls to JSONL

Replace real CLI dependencies (e.g. `gh`) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: `subprocess_runner = ['python3', 'fake_gh.py']`; assert behavior by parsing the log: `json.loads(log_path.read_text())`. See also: testing — Concurrent JSONL appends: assert exact line counts.

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
