---
id: 0304
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.881299+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Subprocess CLI test stubs: log invocations to JSONL

Replace real CLI dependencies in tests with a small Python script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

```python
subprocess_runner = ['python3', 'fake_gh.py']
# assert via json.loads(log_path.read_text())
```

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
