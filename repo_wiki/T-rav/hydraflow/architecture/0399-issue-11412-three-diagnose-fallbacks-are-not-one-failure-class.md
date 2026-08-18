---
id: 0399
topic: architecture
source_issue: 11412
source_phase: plan
created_at: 2026-08-18T02:58:42.910227+00:00
status: active
corroborations: 1
---

# Three diagnose() fallbacks are not one failure class

`DiagnosticRunner.diagnose()` has three fallback branches with distinct semantics. Only two are INFRA-classifiable under failover: the `parsed is None` branch (no JSON emitted ⇒ run cut off) and the `DiagnosisResult.model_validate` exception (parsed-but-invalid block). The post-`_execute` `except Exception` → "Diagnostic agent crashed" fallback must keep `infra_failure=False`.

**Why:** Parking a crashed spawn behind a cooldown strands genuine crashes outside the structured-output-attrition class that #11370/#11412 scope.
