# ARCH-0003: The governance layer is "the Council, with chambers"

**Date:** 2026-08-25 · **Seats:** operator (house ruling for every PAAA org) + session clerk · **Verdict:** ACCEPT
**Dissent:** none
**Enforcement:** enforced
**Enforced by:** `make council-conformance` (scripts/check_council_conformance.py)
**Evidence:** GNAA decision record `council/decisions/general/0009` (goodneighboraviation.org — the precedent that settled the family on *Council*) · Mnemo PAAA note `3-Resources/Purpose Articles Actors Artifacts…` (the written house standard) · ARCH-0001 (the console charter this renames, kept intact) · #11741

The layer chartered as *the console* in ARCH-0001 is renamed **the Council**; its panels are **chambers**. "Console" names a control surface, not a deliberative structure — chambers, chairs, seats, verdicts, and recusal all belong to a council, and the word was already doing double duty against this repo's operator console (the dashboard). The intermediate GNAA name *Board* was withdrawn by that org's governance review: fiduciary-adjacent names invite a confusion this layer cannot afford, since a chamber holds no merge authority, no money, and no policy. Mechanically: `agents/console/` → `agents/council/`, `make console-conformance` → `make council-conformance` (old target kept as a deprecated alias), `scripts/check_console_conformance.py` → `scripts/check_council_conformance.py`, `docs/methodology/consoles-of-personas.md` → `councils-of-personas.md`, and the `console_ledger` CI paths-filter → `council_ledger`.

Records are not retitled. ARCH-0001 and ARCH-0002 keep their era's word and their filenames — `0001-console-charter.md` still reads *console*, and its `Enforced by: make console-conformance` still resolves because the alias stays. Rewriting a merged record to match a later vocabulary is exactly the history-editing the ledger exists to prevent; retiring the alias would falsify that line, so it needs a superseding record rather than a cleanup PR. `repo_wiki/` entries written before this date likewise keep the old name: they are dated, superseded-chained knowledge rows about work that happened under it.
