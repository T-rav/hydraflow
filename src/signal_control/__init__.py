"""Pure control-theory substrate for background workers (Stage 1).

Conditioners turn noisy signals into trustworthy state; controllers drive an
actuator toward a setpoint; HistoricSignalStore is the shared windowed memory.
No module here imports factory code or performs I/O (except the store's opt-in
JSONL path). See docs/superpowers/specs/2026-07-23-bg-worker-control-theory-design.md.
"""
