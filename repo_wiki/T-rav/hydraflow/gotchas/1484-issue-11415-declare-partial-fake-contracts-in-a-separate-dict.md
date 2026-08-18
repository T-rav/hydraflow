---
id: 1484
topic: gotchas
source_issue: 11415
source_phase: plan
created_at: 2026-08-18T03:26:10.006533+00:00
status: active
corroborations: 1
---

# Declare partial-fake contracts in a separate dict

Fakes implementing only a subset of a reference's methods must be listed in a separate `dict[type, frozenset[str]]` mapping fake type to contracted method names.

- `FakeWikiCompiler` implements 4 of 7 `WikiCompiler` methods.
- For dict entries, check only listed names but assert each exists on both sides.
- All other pairs keep the strict "fake implements every reference method" rule.

**Why:** Keeps default strictness for full fakes while allowing intentionally partial fakes, and ensures a method rename on either side still fails the check.
