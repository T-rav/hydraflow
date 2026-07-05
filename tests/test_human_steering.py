from human_steering import parse_directives


def _c(body, ts, login="alice"):
    return {"user": {"login": login}, "body": body, "created_at": ts}


_ALICE = frozenset({"alice"})


def test_steer_is_latest_wins_declarative():
    d = parse_directives(
        [
            _c("/steer do X", "2026-07-03T10:00:00Z"),
            _c("/steer do Y", "2026-07-03T10:01:00Z"),
        ],
        None,
        _ALICE,
    )
    assert d.guidance == "do Y"
    assert d.flow == "running"


def test_pause_then_resume_declarative():
    d = parse_directives(
        [_c("/pause", "2026-07-03T10:00:00Z"), _c("/resume", "2026-07-03T10:01:00Z")],
        None,
        _ALICE,
    )
    assert d.flow == "running"
    d2 = parse_directives(
        [_c("/resume", "2026-07-03T10:00:00Z"), _c("/pause", "2026-07-03T10:01:00Z")],
        None,
        _ALICE,
    )
    assert d2.flow == "paused"


def test_abort_precedence_over_pause_and_steer():
    d = parse_directives(
        [
            _c("/steer x", "2026-07-03T10:00:00Z"),
            _c("/pause", "2026-07-03T10:01:00Z"),
            _c("/abort", "2026-07-03T10:02:00Z"),
        ],
        None,
        _ALICE,
    )
    assert d.flow == "abort"


def test_redo_fires_once_via_high_water_mark():
    comments = [_c("/redo shape", "2026-07-03T10:00:00Z")]
    d = parse_directives(comments, None, _ALICE)
    assert d.redo_phase == "shape"
    assert d.new_last_applied_ts == "2026-07-03T10:00:00Z"
    # re-poll with the mark advanced: redo must NOT re-fire
    d2 = parse_directives(comments, "2026-07-03T10:00:00Z", _ALICE)
    assert d2.redo_phase is None


def test_non_directive_and_malformed_ignored():
    d = parse_directives(
        [
            _c("just a comment", "2026-07-03T10:00:00Z"),
            _c("/bogus thing", "2026-07-03T10:01:00Z"),
        ],
        None,
        _ALICE,
    )
    assert d.guidance is None and d.flow == "running" and d.redo_phase is None


def test_only_authorized_author_is_honored():
    cs = [
        {
            "user": {"login": "bob"},
            "body": "/pause",
            "created_at": "2026-07-04T10:00:00Z",
        }
    ]
    assert (
        parse_directives(cs, None, frozenset({"alice"})).flow == "running"
    )  # bob not allowed
    assert (
        parse_directives(cs, None, frozenset({"bob"})).flow == "paused"
    )  # bob allowed


def test_empty_allowlist_honors_nobody():
    cs = [
        {
            "user": {"login": "alice"},
            "body": "/abort",
            "created_at": "2026-07-04T10:00:00Z",
        }
    ]
    assert parse_directives(cs, None, frozenset()).flow == "running"  # empty ⇒ nobody
