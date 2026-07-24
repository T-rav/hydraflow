"""Second-order vitals — the residual monitor over the instrument set (#10373).

The capstone falsification instrument. Where each first-order instrument
(escape ledger, erosion trends, intervention tally, sampled re-audit,
judge-independence) watches ONE second-order dimension and files its own
findings, this package computes the JOINT condition none of them can see:
correlated adverse drift across several independent instruments WHILE the
primary gates stay green — green-while-dying, residual monitoring under
analytical redundancy.

Pure package (no IO beyond reading the instruments' own ledgers): control
limits + counting only, because legibility is the feature in the instrument
that has to be trusted when it fires. The :class:`~second_order_vitals_loop`
caretaker wires these into an ADR-0029 Pattern-B loop.
"""

from __future__ import annotations
