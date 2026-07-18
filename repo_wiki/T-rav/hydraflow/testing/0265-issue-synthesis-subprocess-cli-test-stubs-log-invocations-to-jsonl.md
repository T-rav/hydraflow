---
id: 0265
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.483942+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Subprocess CLI test stubs: log invocations to JSONL

Replace real CLI dependencies in tests with a small Python script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

```python
subprocess_runner = ['python3', 'fake_gh.py']
# assert via json.loads(log_path.read_text())
```

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
