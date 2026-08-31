---
id: 0429
topic: architecture
source_issue: 11544
source_phase: plan
created_at: 2026-08-30T15:37:21.169351+00:00
status: active
corroborations: 1
---

# Derive bypass guard seam list from registry, not hardcode

When writing architecture ratchets against direct provider credential resolution, enumerate seams dynamically from the runtime registry rather than a hardcoded list.

Example: `tests/architecture/test_no_governed_direct_bypass.py` should read the runtime registry to find spawn sites resolving credentials outside the resolver, reddening if a new seam appears in a governed repo.

**Why:** Hardcoded lists rot when new spawn sites are added, allowing silent bypasses of the `gateway_governed_repos` policy resolver.
