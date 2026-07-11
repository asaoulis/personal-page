"""Worker resume state, persisted next to the results as `state.json`.

The cron is stateless across runs and best-effort in timing, so the worker must be
resumable: it remembers the newest processed origin time + recently-processed ids
(for de-duplication) and the measured archive lag.  NOT served to the frontend.

Schema-2 (this file) adds a *per-event state machine* on top of the legacy fields so a
one-shot cron tick can drive every event one step and exit: `State.events` maps a stable
event id to an `EventStatus` (status, retry count, next-retry time, first-seen, error).
Everything serialises to JSON each tick — no in-memory-only progress.  `State.load` still
reads legacy files that predate `events` (the field simply defaults empty).

Per-event lifecycle:

    register ->  pending
                   |  (data present, inference run)
                   v
    data_waiting <-> inferred  ->  published        (terminal: ok)
         |
         `-- schedule_retry (exponential backoff) ... -> failed   (terminal: exhausted)

`pending`/`data_waiting`/`inferred` are non-terminal; `published`/`failed` are terminal.
Archive-lagged F-net downloads legitimately retry for days, so `max_attempts` defaults to 20.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional

from .util import from_iso, to_iso, utcnow

# Non-terminal vs terminal per-event statuses.
PENDING = "pending"
DATA_WAITING = "data_waiting"
INFERRED = "inferred"
PUBLISHED = "published"
FAILED = "failed"
# Terminal: recognised at registration as outside the model's domain (e.g. too deep) — never
# downloaded, never retried, never published.
OUT_OF_DOMAIN = "out_of_domain"
# Terminal: a provisional (USGS-discovered, reference-pending) event replaced by the matching
# F-net solution — `superseded_by` links to the F-net id, so neither is ever re-inferred.
SUPERSEDED = "superseded"

TERMINAL_STATUSES = frozenset({PUBLISHED, FAILED, OUT_OF_DOMAIN, SUPERSEDED})


@dataclass
class EventStatus:
    """Per-event resume state (one entry in `State.events`)."""

    status: str = PENDING
    attempts: int = 0
    next_retry_at: Optional[str] = None  # ISO; None => due immediately
    first_seen: Optional[str] = None  # ISO
    last_error: Optional[str] = None
    published_at: Optional[str] = None  # ISO
    # Candidate origin metadata, stamped at registration — lets a later F-net solution be
    # matched (space-time) against a provisional event even when the original candidate has
    # dropped out of the poll window.  All optional (legacy files predate them).
    origin_time: Optional[str] = None  # ISO
    lat: Optional[float] = None
    lon: Optional[float] = None
    # True for a USGS-discovered candidate (no F-net MT yet: record published with the
    # reference pending); False for an F-net solution.
    provisional: bool = False
    # id of the F-net event that superseded this provisional one (status == SUPERSEDED).
    superseded_by: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _jitter_factor(seed: str, spread: float = 0.20) -> float:
    """Deterministic multiplicative jitter in [1-spread, 1+spread], seeded by `seed`.

    Deterministic so a resumed tick reproduces the SAME backoff (no drift on restart) and so
    tests are exact.  Derived from a stable hash of the seed string, not `random` global state.
    """
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    frac = h / 0xFFFFFFFF  # [0, 1]
    return 1.0 + (2.0 * frac - 1.0) * spread


@dataclass
class State:
    last_time: Optional[str] = None  # ISO of newest processed origin time
    processed_ids: List[str] = field(default_factory=list)
    archive_lag_minutes: Optional[float] = None
    updated: Optional[str] = None
    events: Dict[str, EventStatus] = field(default_factory=dict)

    # ---------------------------------------------------------------- persistence
    @classmethod
    def from_dict(cls, d: dict) -> "State":
        """Rebuild a State from parsed JSON, tolerating legacy files with no `events` key
        (and any missing/None scalar field, which falls back to its dataclass default)."""
        raw_events = d.get("events") or {}
        events = {
            eid: EventStatus(**{k: ev[k] for k in EventStatus.__dataclass_fields__
                                if k in ev and ev[k] is not None})
            for eid, ev in raw_events.items()
        }
        kwargs = {}
        for k in cls.__dataclass_fields__:
            if k == "events":
                continue
            if k in d and d[k] is not None:
                kwargs[k] = d[k]
        kwargs["events"] = events
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str) -> "State":
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            return cls.from_dict(d)
        return cls()

    def remember(self, event_id: str, max_ids: int) -> None:
        if event_id not in self.processed_ids:
            self.processed_ids.append(event_id)
        if len(self.processed_ids) > max_ids:
            self.processed_ids = self.processed_ids[-max_ids:]

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.updated = to_iso(utcnow())
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    # ---------------------------------------------------------------- state machine
    def register(self, event_id: str, now, *, origin_time: Optional[str] = None,
                 lat: Optional[float] = None, lon: Optional[float] = None,
                 provisional: bool = False) -> EventStatus:
        """Idempotently introduce an event as `pending`.  Returns its EventStatus.

        Never resets an event already known (so a re-poll of the same event doesn't wipe its
        retry count / terminal verdict); origin metadata is back-filled if it was missing
        (legacy entries predate the fields)."""
        st = self.events.get(event_id)
        if st is None:
            st = EventStatus(status=PENDING, first_seen=to_iso(now), origin_time=origin_time,
                             lat=lat, lon=lon, provisional=provisional)
            self.events[event_id] = st
        else:
            if st.origin_time is None:
                st.origin_time = origin_time
            if st.lat is None:
                st.lat = lat
            if st.lon is None:
                st.lon = lon
        return st

    def due(self, now) -> List[str]:
        """Non-terminal event ids whose `next_retry_at` is None or in the past, oldest-due first.

        Ordering: by effective due time (`next_retry_at` or `first_seen`), then id — stable and
        resume-invariant."""
        now_iso = to_iso(now)
        due_ids = []
        for eid, st in self.events.items():
            if st.terminal:
                continue
            if st.next_retry_at is None or st.next_retry_at <= now_iso:
                due_ids.append(eid)
        due_ids.sort(key=lambda e: (self.events[e].next_retry_at or self.events[e].first_seen or "", e))
        return due_ids

    def advance(self, event_id: str, status: str, now) -> EventStatus:
        """Move an event to `status` (registering it first if unknown).  Stamps `published_at`
        when it reaches `published`."""
        st = self.events.get(event_id) or self.register(event_id, now)
        st.status = status
        if status == PUBLISHED and st.published_at is None:
            st.published_at = to_iso(now)
        return st

    def mark_superseded(self, event_id: str, superseded_by: str, now) -> EventStatus:
        """Move a provisional event to the terminal `superseded` status, linking the F-net id
        that replaces it (the alias): neither id is ever re-inferred.  Clears any pending
        retry."""
        st = self.events.get(event_id) or self.register(event_id, now)
        st.status = SUPERSEDED
        st.superseded_by = superseded_by
        st.next_retry_at = None
        return st

    def mark_out_of_domain(self, event_id: str, now, *, error: Optional[str] = None) -> EventStatus:
        """Move an event to the terminal `out_of_domain` status (registering it first if unknown).

        Clears any pending retry so it is never due again; retains `last_error` for the operator.
        Used by the monitor's registration-time filter for candidates outside the model domain."""
        st = self.events.get(event_id) or self.register(event_id, now)
        st.status = OUT_OF_DOMAIN
        st.next_retry_at = None
        if error is not None:
            st.last_error = error
        return st

    def schedule_retry(
        self,
        event_id: str,
        now,
        *,
        base_s: int = 1800,
        cap_s: int = 43200,
        max_attempts: int = 20,
        error: Optional[str] = None,
    ) -> EventStatus:
        """Bump the attempt counter and set `next_retry_at = now + backoff`.

        Backoff is exponential (`base_s * 2**(attempts-1)`) clamped to `cap_s`, with ±20%
        deterministic jitter seeded on `event_id:attempts`.  When `attempts` reaches
        `max_attempts` the event goes terminal `failed` (with `last_error` retained)."""
        st = self.events.get(event_id) or self.register(event_id, now)
        st.attempts += 1
        if error is not None:
            st.last_error = error
        if st.attempts >= max_attempts:
            st.status = FAILED
            st.next_retry_at = None
            return st
        raw = base_s * (2 ** (st.attempts - 1))
        delay = min(cap_s, raw) * _jitter_factor(f"{event_id}:{st.attempts}")
        st.next_retry_at = to_iso(now + timedelta(seconds=delay))
        return st
