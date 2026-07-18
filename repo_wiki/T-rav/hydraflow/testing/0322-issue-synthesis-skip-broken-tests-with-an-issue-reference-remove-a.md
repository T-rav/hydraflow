---
id: 0322
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.894008+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Skip broken tests with an issue reference; remove after fix

Mark broken tests with a referenced issue, never a bare skip.

```python
@pytest.mark.skip(reason="documenting bug: #1234")
```

Remove the skip immediately after the issue is resolved.

**Why:** Without an issue reference, skipped tests become permanent dead weight with no path to removal or triage.
