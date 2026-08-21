# HydraFlow factory task state

HydraFlow stores phase-task state directly in each implementation worktree's
`.beads/issues.jsonl`. `src/beads_manager.py` is the sole writer: it validates
the graph, locks the store, and replaces it atomically.

The database-backed Beads CLI is not part of this repository's supported
runtime. Do not install or invoke `bd`, and do not start, migrate, pull, or push
a Dolt database. No database locator, CLI config, or hook template is shipped.
Git uses the repository's `.githooks/` path.

Agents may see phase IDs in an implementation prompt, but HydraFlow owns every
claim and close transition. Do not edit `issues.jsonl` by hand.
