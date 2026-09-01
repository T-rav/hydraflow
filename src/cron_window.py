"""A 5-field cron matcher, and "did this fire since I last looked?".

`charter.yaml` v2 declares loop schedules as cron clauses (ADR-0145). The
schema validates the SHAPE at parse time; this evaluates them.

**Written rather than depended on, deliberately.** The runtime dependency list
is ten packages, and a scheduler library brings a scheduler — timezone
policy, DST handling, catch-up semantics — where what is needed is one
question: has a window passed. The trade is real and the mitigation is that
this module is pure and heavily tested; the risk of a hand-rolled matcher is
silent wrongness, so it is the tests that make this the cheaper option, not
the code.

**Supported:** `*`, integers, `a-b` ranges, `a,b,c` lists, `*/n` and `a-b/n`
steps, and three-letter month/day names (`MON`, `JAN`, case-insensitive).
Fields are `minute hour day-of-month month day-of-week`, with day-of-week
`0`/`7` both Sunday.

**Not supported, and rejected loudly rather than mis-parsed:** `@weekly` and
friends, seconds, `L`/`W`/`#` (Quartz extensions), and the Vixie
"day-of-month OR day-of-week when both are restricted" disjunction — this
module ANDs them, which is what a reader of `0 9 1 * MON` expects and what the
declaration means. A charter using an unsupported form fails at parse, never
silently never-fires.

All times are UTC. A charter that meant a local wall-clock hour and got UTC is
a scheduling bug either way; making it uniform means it is at least the same
bug everywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ],
        start=1,
    )
}
_DAYS = {
    name: index
    for index, name in enumerate(
        ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"], start=0
    )
}

#: (low, high) inclusive for each field, in order.
_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_FIELD_COUNT = 5

#: How far back :func:`fired_since` will walk. 40 days of minutes covers every
#: expressible monthly schedule with room to spare; beyond that the answer is
#: "long enough ago that a catch-up is not wanted anyway", and an unbounded
#: walk on a malformed-but-valid expression would hang a loop tick.
_MAX_LOOKBACK_MINUTES = 40 * 24 * 60


class CronError(ValueError):
    """An expression this module refuses to guess at."""


def _token(raw: str, index: int) -> int:
    text = raw.strip().upper()
    if index == 3 and text in _MONTHS:
        return _MONTHS[text]
    if index == 4 and text in _DAYS:
        return _DAYS[text]
    try:
        return int(text)
    except ValueError as exc:
        msg = f"cron field {index} has unparseable value {raw!r}"
        raise CronError(msg) from exc


def _parse_field(raw: str, index: int) -> frozenset[int]:
    low, high = _BOUNDS[index]
    allowed: set[int] = set()
    for part in raw.split(","):
        body, _, step_text = part.partition("/")
        try:
            step = int(step_text) if step_text else 1
        except ValueError as exc:
            msg = f"cron field {index} has a non-integer step in {part!r}"
            raise CronError(msg) from exc
        if step < 1:
            msg = f"cron field {index} has a non-positive step in {part!r}"
            raise CronError(msg)
        if body.strip() == "*":
            start, end = low, high
        elif "-" in body.strip().lstrip("-"):
            start_text, _, end_text = body.partition("-")
            start, end = _token(start_text, index), _token(end_text, index)
        else:
            start = end = _token(body, index)
            if step_text:
                # `5/15` means "from 5, every 15" — a real crontab form.
                end = high
        if start < low or end > high or start > end:
            msg = f"cron field {index} value {part!r} is outside its range {low}-{high}"
            raise CronError(msg)
        allowed.update(range(start, end + 1, step))
    if index == 4 and 7 in allowed:
        # Both 0 and 7 are Sunday; normalise so matching compares one value.
        allowed.discard(7)
        allowed.add(0)
    return frozenset(allowed)


def parse(expression: str) -> tuple[frozenset[int], ...]:
    """Parse a 5-field expression into per-field allowed sets."""
    if expression.strip().startswith("@"):
        msg = (
            f"cron alias {expression!r} is not supported; write the five "
            "fields explicitly so the schedule is readable without knowing "
            "which aliases this implementation happens to accept"
        )
        raise CronError(msg)
    fields = expression.split()
    if len(fields) != _FIELD_COUNT:
        msg = (
            f"cron expression {expression!r} has {len(fields)} fields; "
            f"{_FIELD_COUNT} are required (minute hour day-of-month month "
            "day-of-week)"
        )
        raise CronError(msg)
    return tuple(_parse_field(field, index) for index, field in enumerate(fields))


def matches(expression: str, when: datetime) -> bool:
    """Does *when* (to the minute, UTC) satisfy *expression*?

    Day-of-month and day-of-week are ANDed. Vixie cron ORs them when both are
    restricted; that behaviour surprises everyone who has not read the man
    page, and a charter is read by people declaring intent, not by cron
    archaeologists. The module docstring says so rather than leaving it to be
    discovered.
    """
    minute, hour, dom, month, dow = parse(expression)
    stamped = when.astimezone(UTC)
    return (
        stamped.minute in minute
        and stamped.hour in hour
        and stamped.day in dom
        and stamped.month in month
        # `isoweekday() % 7` maps Monday=1..Sunday=7 onto cron's Sunday=0.
        and (stamped.isoweekday() % 7) in dow
    )


def fired_since(
    expression: str, last: datetime | None, now: datetime
) -> datetime | None:
    """The most recent firing in ``(last, now]``, or None if there was none.

    Returns the WINDOW, not a count. The catch-up policy is deliberate: a loop
    fires at most once per tick and never backfills missed windows, because a
    factory that was down for a day should not wake up and run a daily loop
    thirty times. The caller records the skip in its receipt so the decision is
    visible rather than merely silent.

    ``last is None`` means "never fired": the most recent window in the lookback
    counts, so a newly-declared loop runs on its next tick rather than waiting a
    full period.
    """
    cursor = now.astimezone(UTC).replace(second=0, microsecond=0)
    floor = None if last is None else last.astimezone(UTC)
    for _ in range(_MAX_LOOKBACK_MINUTES):
        if floor is not None and cursor <= floor:
            return None
        if matches(expression, cursor):
            return cursor
        cursor -= timedelta(minutes=1)
    return None
