"""Declarative branch-protection gate contract: source of truth + generators.

The contract lives at ``docs/standards/branch_protection/gates.toml``. From it
we generate the per-branch ruleset JSON and the README gate table, and we
validate that every active gate's check context is produced by a real CI job.
See ``docs/adr`` (declarative gate contract) and ADR-0042 §Enforcement.
"""
