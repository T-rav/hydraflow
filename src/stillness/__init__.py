"""Stillness — the control-systems rework of the factory (#10819 umbrella).

The factory ran as ~70 uncoordinated finding-driven loops on one codebase, and
over a hands-off fortnight its flux *grew* as real work shrank — a limit cycle.
This package holds the instruments and (later) the regulators that damp it.

First tenant: :mod:`stillness.fingerprint` — the read-only oscillation
fingerprint (#10820) that ranks the flux carriers before any damper is built.
Acceptance instrument: :mod:`stillness.decay` — the quiet-week decay curve
(#10822) that classifies a freeze window as decaying-to-floor (healthy) or
self-sustaining hunting (the factory as its own disturbance source).
Sensing fix: :mod:`stillness.settling` — settling-window sensing (#10825, rung 1
of ADR-0120's innovation-filtered-sensing ladder) that suppresses readings from
an area for a window after actuating there, so a loop can't read its own
actuation as a disturbance.
"""
