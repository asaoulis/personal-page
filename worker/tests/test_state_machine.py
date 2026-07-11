import json
from datetime import datetime, timedelta, timezone

from fnet_monitor.state import (
    DATA_WAITING,
    FAILED,
    INFERRED,
    PENDING,
    PUBLISHED,
    EventStatus,
    State,
)
from fnet_monitor.util import from_iso

NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- register
def test_register_is_idempotent_and_pending():
    s = State()
    st = s.register("e1", NOW)
    assert st.status == PENDING and st.attempts == 0
    assert st.first_seen == "2026-06-28T12:00:00Z"
    st.attempts = 3  # mutate
    again = s.register("e1", NOW + timedelta(hours=1))  # must NOT reset
    assert again.attempts == 3
    assert again.first_seen == "2026-06-28T12:00:00Z"
    assert len(s.events) == 1


# --------------------------------------------------------------------------- due
def test_due_excludes_terminal_and_future():
    s = State()
    s.register("pending", NOW)
    s.advance("published", PUBLISHED, NOW)
    s.advance("failed", FAILED, NOW)
    s.register("future", NOW)
    s.events["future"].next_retry_at = "2026-06-28T13:00:00Z"  # in the future
    s.register("past", NOW)
    s.events["past"].next_retry_at = "2026-06-28T11:00:00Z"  # in the past
    due = s.due(NOW)
    assert "published" not in due and "failed" not in due
    assert "future" not in due
    assert set(due) == {"pending", "past"}


def test_due_ordering_by_effective_due_time():
    s = State()
    # first_seen oldest -> earliest; explicit next_retry overrides
    s.register("b", NOW)
    s.register("a", NOW - timedelta(hours=2))
    s.register("c", NOW)
    s.events["c"].next_retry_at = "2026-06-28T09:00:00Z"  # earliest effective
    assert s.due(NOW) == ["c", "a", "b"]


# --------------------------------------------------------------------------- advance
def test_advance_transitions_and_stamps_published():
    s = State()
    s.register("e", NOW)
    s.advance("e", DATA_WAITING, NOW)
    assert s.events["e"].status == DATA_WAITING
    s.advance("e", INFERRED, NOW)
    assert s.events["e"].status == INFERRED
    st = s.advance("e", PUBLISHED, NOW)
    assert st.status == PUBLISHED and st.terminal
    assert st.published_at == "2026-06-28T12:00:00Z"


def test_advance_registers_unknown_event():
    s = State()
    s.advance("new", DATA_WAITING, NOW)
    assert "new" in s.events and s.events["new"].status == DATA_WAITING


# --------------------------------------------------------------------------- backoff
def _delay_seconds(iso_next, now):
    return (from_iso(iso_next) - now).total_seconds()


def test_schedule_retry_backoff_grows_and_caps():
    s = State()
    s.register("e", NOW)
    delays = []
    for _ in range(8):
        st = s.schedule_retry("e", NOW, base_s=1800, cap_s=43200, max_attempts=99)
        delays.append(_delay_seconds(st.next_retry_at, NOW))
    # attempts 1..8: nominal 1800,3600,7200,14400,28800,(57600->cap),(cap),(cap)
    nominal = [1800, 3600, 7200, 14400, 28800, 43200, 43200, 43200]
    for d, nom in zip(delays, nominal):
        assert 0.8 * nom - 1 <= d <= 1.2 * nom + 1  # within +/-20% jitter
    # capped tail never exceeds cap*1.2
    assert all(d <= 43200 * 1.2 + 1 for d in delays)


def test_schedule_retry_jitter_is_deterministic():
    s1, s2 = State(), State()
    s1.register("e", NOW)
    s2.register("e", NOW)
    a = s1.schedule_retry("e", NOW)
    b = s2.schedule_retry("e", NOW)
    assert a.next_retry_at == b.next_retry_at  # same seed -> same jitter


def test_schedule_retry_marks_failed_after_max_attempts():
    s = State()
    s.register("e", NOW)
    st = None
    for _ in range(5):
        st = s.schedule_retry("e", NOW, max_attempts=5, error="boom")
    assert st.status == FAILED and st.terminal
    assert st.next_retry_at is None
    assert st.last_error == "boom"
    assert "e" not in s.due(NOW)  # terminal -> not due


# --------------------------------------------------------------------------- persistence / resume
def test_resume_from_disk_preserves_decisions(tmp_path):
    p = str(tmp_path / "state.json")
    s = State(last_time="2026-06-01T00:00:00Z")
    s.register("done", NOW)
    s.advance("done", PUBLISHED, NOW)
    s.register("waiting", NOW)
    s.schedule_retry("waiting", NOW, error="no data yet")
    s.save(p)

    s2 = State.load(p)
    assert s2.last_time == "2026-06-01T00:00:00Z"
    assert isinstance(s2.events["done"], EventStatus)
    assert s2.events["done"].status == PUBLISHED
    assert s2.events["done"].published_at == s.events["done"].published_at
    assert s2.events["waiting"].attempts == 1
    assert s2.events["waiting"].last_error == "no data yet"
    assert s2.events["waiting"].next_retry_at == s.events["waiting"].next_retry_at
    # same due() decision after reload
    later = from_iso(s.events["waiting"].next_retry_at) + timedelta(seconds=1)
    assert s.due(later) == s2.due(later)


def test_load_legacy_state_file_without_events(tmp_path):
    p = tmp_path / "old_state.json"
    # a pre-schema-2 file: no `events` key at all
    p.write_text(json.dumps({
        "last_time": "2026-05-01T00:00:00Z",
        "processed_ids": ["a", "b"],
        "archive_lag_minutes": 42.0,
        "updated": "2026-05-01T00:05:00Z",
    }))
    s = State.load(str(p))
    assert s.last_time == "2026-05-01T00:00:00Z"
    assert s.processed_ids == ["a", "b"]
    assert s.archive_lag_minutes == 42.0
    assert s.events == {}  # defaults clean
    assert s.due(NOW) == []
    # and it can still be driven forward + re-saved
    s.register("newone", NOW)
    s.save(str(p))
    assert State.load(str(p)).events["newone"].status == PENDING
