from human_steering import parse_directives


def _c(body, ts, login="alice"):
    return {"user": {"login": login}, "body": body, "created_at": ts}


def test_steer_is_latest_wins_declarative():
    d = parse_directives(
        [
            _c("/steer do X", "2026-07-03T10:00:00Z"),
            _c("/steer do Y", "2026-07-03T10:01:00Z"),
        ],
        None,
    )
    assert d.guidance == "do Y"
    assert d.flow == "running"


def test_pause_then_resume_declarative():
    d = parse_directives(
        [_c("/pause", "2026-07-03T10:00:00Z"), _c("/resume", "2026-07-03T10:01:00Z")],
        None,
    )
    assert d.flow == "running"
    d2 = parse_directives(
        [_c("/resume", "2026-07-03T10:00:00Z"), _c("/pause", "2026-07-03T10:01:00Z")],
        None,
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
    )
    assert d.flow == "abort"


def test_redo_fires_once_via_high_water_mark():
    comments = [_c("/redo shape", "2026-07-03T10:00:00Z")]
    d = parse_directives(comments, None)
    assert d.redo_phase == "shape"
    assert d.new_last_applied_ts == "2026-07-03T10:00:00Z"
    # re-poll with the mark advanced: redo must NOT re-fire
    d2 = parse_directives(comments, "2026-07-03T10:00:00Z")
    assert d2.redo_phase is None


def test_non_directive_and_malformed_ignored():
    d = parse_directives(
        [
            _c("just a comment", "2026-07-03T10:00:00Z"),
            _c("/bogus thing", "2026-07-03T10:01:00Z"),
        ],
        None,
    )
    assert d.guidance is None and d.flow == "running" and d.redo_phase is None
