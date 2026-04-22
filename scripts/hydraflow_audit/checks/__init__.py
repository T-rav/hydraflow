"""Registering all check modules.

Import each principle module so its `@register(...)` decorators fire. Unimplemented
principles (no module imported, or rows without a matching function) surface as
NOT_IMPLEMENTED findings — by design, to keep ADR-0044 and the audit in lockstep.
"""

from . import p1_docs  # noqa: F401
