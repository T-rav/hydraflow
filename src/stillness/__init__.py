"""Stillness — the control-systems rework of the factory (#10819 umbrella).

The factory ran as ~70 uncoordinated finding-driven loops on one codebase, and
over a hands-off fortnight its flux *grew* as real work shrank — a limit cycle.
This package holds the instruments and (later) the regulators that damp it.

First tenant: :mod:`stillness.fingerprint` — the read-only oscillation
fingerprint (#10820) that ranks the flux carriers before any damper is built.
"""
