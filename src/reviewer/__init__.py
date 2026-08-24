"""Back-compat re-exports for the ``reviewer`` package.

The original ``src/reviewer.py`` (a 983-LOC, 21-method ``ReviewRunner``) was
split into this package for mass discipline (Refs #11547), the same shape
``agent/``, ``review_phase/`` and ``implement_phase/`` already use. Existing
imports keep working::

    from reviewer import ReviewRunner   # still works
    import reviewer                     # still works

Layout:
  * ``_runner.py``   — construction and ``review()``: what the class IS.
  * ``_prompts.py``  — every prompt it builds. ``_build_review_prompt_with_stats``
    alone was a quarter of the original file.
  * ``_fixes.py``    — ``fix_ci`` / ``fix_review_findings`` and the outcome
    record they share.
  * ``_parsing.py``  — verdict extraction and input bounding: the methods a
    malformed agent reply reaches first.
  * ``_repo.py``     — git reads about the branch under review.
  * ``_context.py``  — evidence gathered before the reviewer runs.

Each slice is a mixin ``ReviewRunner`` inherits, so there is exactly ONE class
identity and every ``patch.object(ReviewRunner, ...)`` target still resolves.

**Patch targets follow their call site.** Module-level names the tests reach
through (``logger``, ``discover_plugin_skills``) are bound in the module that
CALLS them, so ``patch("reviewer.logger")`` would replace an attribute here and
leave the real binding untouched — a patch that silently no-ops. They are
deliberately NOT re-exported: patch ``reviewer._prompts.logger`` /
``reviewer._prompts.discover_plugin_skills`` instead, so a stale target fails
loudly rather than passing while testing nothing.
"""

from __future__ import annotations

from ._runner import ReviewRunner

__all__ = ["ReviewRunner"]
