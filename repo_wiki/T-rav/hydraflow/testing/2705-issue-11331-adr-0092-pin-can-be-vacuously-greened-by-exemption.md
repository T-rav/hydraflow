---
id: 2705
topic: testing
source_issue: 11331
source_phase: plan
created_at: 2026-08-16T09:57:29.108944+00:00
status: active
corroborations: 1
---

# ADR-0092 pin can be vacuously greened by exemption vocabulary

When amending ADR-0092 to mark a site as restricted, never use standalone words `exempt`, `trusted`, or `unrestricted` in the same paragraph as the site name. The regression pins use `hardened or _adr_documents_exemption(...)`, so such wording satisfies the pin vacuously.

- Write amendments as "these sites are now restricted."
- `agent_unrestricted_tools` is safe — no word boundary before `unrestricted`.

**Why:** A later regression that re-enables `bypassPermissions` would go undetected because the pin already passes via the exemption clause without testing the actual command shape.
