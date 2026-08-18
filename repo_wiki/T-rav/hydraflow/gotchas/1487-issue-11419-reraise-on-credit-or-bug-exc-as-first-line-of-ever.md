---
id: 1487
topic: gotchas
source_issue: 11419
source_phase: plan
created_at: 2026-08-18T03:36:18.966883+00:00
status: active
corroborations: 1
---

# reraise_on_credit_or_bug(exc) as first line of every except Exception

In `src/report_issue_loop.py`, any `except Exception:` block must become `except Exception as exc:` with `reraise_on_credit_or_bug(exc)` as its first statement. This pattern is already established at lines ~189, ~266, ~398.

```python
except Exception as exc:
    reraise_on_credit_or_bug(exc)
    logger.warning("...", exc_info=True)
```

**Why:** Bare `except Exception:` swallows real bugs (TypeError, AttributeError) alongside the intended retryable failures, leaving verification loops silently no-op.
