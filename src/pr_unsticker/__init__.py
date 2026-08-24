"""Back-compat re-exports for the ``pr_unsticker`` package.

``src/pr_unsticker.py`` held a 903-LOC, 20-method ``PRUnsticker``. Split for
mass discipline (Refs #11547), the shape ``agent/``, ``reviewer/`` and
``workspace/`` already use. Existing imports keep working::

    from pr_unsticker import PRUnsticker   # still works

Layout:
  * ``_unsticker.py``  — construction and the two-phase round loop
    (``unstick`` + ``_process_item``): what the class IS.
  * ``_causes.py``     — the cause vocabulary. The keyword tuples, the enum,
    the priority table and ``_classify_cause`` travel WITH the methods that
    read them; a constant left behind is the classic split defect (#11658).
  * ``_resolve.py``    — cause -> fix dispatch and the non-timeout repairs.
  * ``_timeout.py``    — the CI-timeout path. Separate because a timeout
    arrives with NO evidence: it has to manufacture some (isolate the hanging
    tests, name the language) before a prompt can say anything specific.
  * ``_prompts.py``    — the two Claude-bound prompt builders, both registered
    and rubric-scored in ``scripts/audit_prompts.py``.
  * ``_reflection.py`` — troubleshooting-pattern capture and fix reflection:
    knowledge work that runs after the outcome and must never change it.
  * ``_merge.py``      — the serial merge phase, the re-rebase it forces on
    everything still queued, and the two terminal dispositions of an item.

Each slice is a mixin ``PRUnsticker`` inherits, so there is exactly ONE class
identity and every ``patch.object(PRUnsticker, ...)`` target still resolves.

**Patch targets follow their call site.** A module-level name a test reaches
through is bound in the module that CALLS it, so ``patch("pr_unsticker.X")``
would replace an attribute here and leave the real binding untouched — a patch
that silently no-ops. Patch ``pr_unsticker._merge.X`` /
``pr_unsticker._timeout.X`` instead, so a stale target fails loudly.

``FailureCause``, ``_classify_cause`` and ``_CAUSE_PRIORITY`` are deliberately
NOT re-exported, even though the old module published them and the tests
imported them from here. A re-export is a SECOND name for the same object, and
the second name is the one that rebinds without effect: ``patch.object(
pr_unsticker, "_classify_cause", ...)`` would replace this attribute while
every slice keeps reading its own module global, so the patch passes while
testing nothing. That is not hypothetical — a batch-6 review found exactly this
shape make two single-registry guards vacuous. Import them from
``pr_unsticker._causes``, where a stale target raises instead.
"""

from __future__ import annotations

from ._unsticker import PRUnsticker

__all__ = ["PRUnsticker"]
