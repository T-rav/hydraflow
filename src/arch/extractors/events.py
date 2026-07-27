"""Extract EventBus publish/subscribe topology from src/.

HydraFlow's ``EventBus`` is a **fan-out** bus by default: an argless
``subscribe()`` / ``subscription()`` returns a queue that receives *every*
published event (``src/events.py``). Since ADR-0114 (#10660) the bus also
supports an *optional* publish-time per-type filter — ``subscribe(types=...)``
/ ``subscription(types=...)`` — so a consumer's queue only receives the
``EventType`` s it asked for. Both shapes coexist: an untyped call is a global
(fan-out) subscriber; a ``types=``-carrying call is a typed subscriber.

This walker collects, from ``src/*.py``:

- **Publishers** — any ``<expr>.publish(...)`` call carrying an ``EventType.X``
  argument (directly or wrapped in ``HydraFlowEvent(type=EventType.X, ...)``).
  The enclosing ``module:Class.func`` becomes the qualified publisher id.
- **Global subscribers** — any *argless* ``<expr>.subscribe(...)`` /
  ``<expr>.subscription(...)`` call site (a fan-out consumer of every event).
  ``self.subscribe`` / ``self.subscription`` calls are ignored — that is the
  bus's own internal plumbing, not a consumer.
- **Typed subscribers** — any ``<expr>.subscribe(types=...)`` /
  ``<expr>.subscription(types=...)`` call site (ADR-0114). Any ``EventType.X``
  members named inside the ``types=`` value are recorded as the filter. A call
  that carries an ``EventType.X`` by some *other* route (the phantom positional
  ``subscribe(EventType.X, ...)`` API the bus never exposed) is still ignored.
- **Declared events** — every member of the ``EventType`` enum, so events with
  a publisher but no live consumer, and events with neither, both surface.
- **Ephemeral allowlist** — the ``EPHEMERAL_EVENT_TYPES`` frozenset (live-only
  events that are never flagged "dead").

An event is "dead" (decided by the generator) only when it is a declared
``EventType`` with no publisher and not on the ephemeral allowlist.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from arch._models import EventBusTopology, EventEdge, TypedSubscriber

_SUBSCRIBE_ATTRS = frozenset({"subscribe", "subscription"})
_EPHEMERAL_ASSIGN_NAME = "EPHEMERAL_EVENT_TYPES"
_EVENT_TYPE_CLASS = "EventType"


def _module_dotted(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)
    return ".".join(rel.with_suffix("").parts)


def _event_names_in(args: list[ast.expr]) -> list[str]:
    """Walk each arg subtree for any ``EventType.X`` attribute access.

    Handles both direct (``bus.publish(EventType.X, ...)``) and wrapped
    (``bus.publish(HydraFlowEvent(type=EventType.X, ...))``) call shapes.
    """
    names: list[str] = []
    for arg in args:
        for sub in ast.walk(arg):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == _EVENT_TYPE_CLASS
            ):
                names.append(sub.attr)
    return names


def _call_carries_event_type(node: ast.Call) -> bool:
    """True if the call passes an ``EventType.X`` value (positional or keyword)."""
    subtrees = list(node.args) + [kw.value for kw in node.keywords]
    return bool(_event_names_in(subtrees))


def _is_none_literal(value: ast.expr) -> bool:
    """True iff *value* is the literal ``None`` (an explicit fan-out request)."""
    return isinstance(value, ast.Constant) and value.value is None


def _types_keyword(node: ast.Call) -> ast.keyword | None:
    """Return the ``types=`` keyword of a subscribe call, if present (ADR-0114).

    ``subscribe(types=frozenset({EventType.X}))`` / ``subscription(types=...)``
    is the optional per-type filter. ``types=None`` is treated as absent (an
    explicit fan-out request), so it is not reported as a typed subscriber.
    """
    for kw in node.keywords:
        if kw.arg == "types" and not _is_none_literal(kw.value):
            return kw
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.publishers: dict[str, list[str]] = defaultdict(list)
        self.global_subscribers: set[str] = set()
        # qualified call site -> the EventType member names it filters on
        # (ADR-0114). A site may appear with an empty set when the filter is a
        # named constant we cannot resolve statically.
        self.typed_subscribers: dict[str, set[str]] = defaultdict(set)
        self.declared_events: set[str] = set()
        self.ephemeral_events: set[str] = set()
        self._fn_stack: list[str] = []

    def _qualified(self) -> str:
        if not self._fn_stack:
            return self.module
        return f"{self.module}:{'.'.join(self._fn_stack)}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == _EVENT_TYPE_CLASS:
            # Collect enum members: ``NAME = "value"`` assignments in the body.
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            self.declared_events.add(target.id)
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def _record_ephemeral(self, value: ast.expr | None) -> None:
        if value is None:
            return
        self.ephemeral_events.update(_event_names_in([value]))

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(
            isinstance(t, ast.Name) and t.id == _EPHEMERAL_ASSIGN_NAME
            for t in node.targets
        ):
            self._record_ephemeral(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            isinstance(node.target, ast.Name)
            and node.target.id == _EPHEMERAL_ASSIGN_NAME
        ):
            self._record_ephemeral(node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "publish":
                for ev in _event_names_in(node.args):
                    self.publishers[ev].append(self._qualified())
            elif func.attr in _SUBSCRIBE_ATTRS:
                self._maybe_record_global_subscriber(node, func)
        self.generic_visit(node)

    def _maybe_record_global_subscriber(
        self, node: ast.Call, func: ast.Attribute
    ) -> None:
        # ``self.subscribe(...)`` / ``self.subscription(...)`` is the bus's own
        # internal plumbing (EventBus.subscription delegates to self.subscribe),
        # never an external consumer.
        if isinstance(func.value, ast.Name) and func.value.id == "self":
            return
        # ``subscribe(types=frozenset({EventType.X, ...}))`` is the ADR-0114
        # per-type filter: a *typed* subscriber, not a fan-out one. Record it
        # with the EventType members named inside the ``types=`` value.
        types_kw = _types_keyword(node)
        if types_kw is not None:
            self.typed_subscribers[self._qualified()].update(
                _event_names_in([types_kw.value])
            )
            return
        # A ``subscribe(EventType.X, ...)`` call with the EventType by some other
        # route is the phantom positional per-type API the bus never exposed —
        # neither a fan-out nor a typed subscriber.
        if _call_carries_event_type(node):
            return
        self.global_subscribers.add(self._qualified())


def extract_event_topology(src_dir: Path) -> EventBusTopology:
    src_dir = Path(src_dir).resolve()
    pubs: dict[str, set[str]] = defaultdict(set)
    global_subs: set[str] = set()
    typed_subs: dict[str, set[str]] = defaultdict(set)
    declared: set[str] = set()
    ephemeral: set[str] = set()
    for py in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        v = _Visitor(_module_dotted(py, src_dir))
        v.visit(tree)
        for ev, lst in v.publishers.items():
            pubs[ev].update(lst)
        global_subs.update(v.global_subscribers)
        for sub, kinds in v.typed_subscribers.items():
            typed_subs[sub].update(kinds)
        declared.update(v.declared_events)
        ephemeral.update(v.ephemeral_events)

    events = sorted(declared | set(pubs))
    return EventBusTopology(
        events=[
            EventEdge(
                event=e,
                publishers=sorted(pubs[e]),
                ephemeral=e in ephemeral,
            )
            for e in events
        ],
        global_subscribers=sorted(global_subs),
        typed_subscribers=[
            TypedSubscriber(subscriber=sub, types=sorted(typed_subs[sub]))
            for sub in sorted(typed_subs)
        ],
    )
