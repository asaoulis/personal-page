"""Live F-net NPE monitor — the supervised tick engine (Phase 3).

One *tick* drives the whole per-event state machine forward by one step and exits, so a
best-effort cron (the GitHub Actions `live-inference.yml` job) can run the real pipeline
statelessly: restore `state.json`, poll the TWO sources (the F-net MT catalogue —
authoritative but days–weeks late — and the USGS FDSN feed for near-live discovery),
filter candidates to the NPE training domain, advance every due event (download ~23 min of
waveforms -> SBI h5 -> NPE inference + FULL QA -> schema-3 record), rebuild the index, save
state.  A USGS-discovered event is PROVISIONAL: inferred from the USGS origin within ~1 h,
published with the F-net reference pending, and superseded by the standard F-net path when
NIED publishes the matching MT (single record under the F-net id; ids aliased in the state).
Resumable by design: a late / skipped / failed run only delays publication.

Run modes
---------
  # ONE tick, then exit — what the CI cron runs (`working-directory: worker`):
  python -m fnet_monitor.monitor --once --out ../_data

  # Local daemon: a tick every --interval seconds, one bad tick never kills the loop:
  python -m fnet_monitor.monitor --loop --interval 1200 --out <dir>

  # BACKFILL (June -> today) — this is NOT a separate module, just the loop with a widened
  # lookback that exits once the only remaining work is future-scheduled retries:
  python -m fnet_monitor.monitor --loop --interval 30 \
      --backfill-start 2026-06-01 --exit-when-drained --out <dir>
  #   Events left in `data_waiting` (F-net archive lag) are EXPECTED leftovers: the drain
  #   check exits when no event is due *now* (future retries don't block); they are reported.

CLI (see `main`): `--once` (default) / `--loop [--interval S=1200]`, `--out DIR` (required),
`--backfill-start ISO` (env `BACKFILL_START`; CLI wins), `--exit-when-drained` (with --loop),
`--publish` (wrap the store in GitBranchStore + publish() after a changed tick — default OFF;
in CI the workflow's own git-push publishes instead), `--no-qa`.
Env overrides (local defaults as fallback): `FNET_CONFIG`, `FNET_CKPT`, `FNET_NSAMPLES`,
`FNET_STATIONS_FILE` (see `live_event`).

Published-vs-inferred convention
--------------------------------
Per due event: run the chain -> `store.upsert(record)` -> `state.advance(id, 'inferred')`
(the record is durable in the store but not yet confirmed published).  At the END of the tick:
  * `--publish`  — call `store.publish()`; on success promote this-tick `inferred` -> `published`.
  * default (CI) — the GitHub Actions git-push step publishes the whole store AFTER this process
    exits and can't report back, so upsert-into-`_data` *is* publication: promote directly to
    `published`.  `store.publish()` is NOT called in this mode.
Either way the event ends terminal (`published`) so it is never re-inferred; only a failure
schedules a retry.  Heavy imports (NpeBackend, torch) are LAZY — module import + `--help` work
with no torch installed, and the NpeBackend singleton is built once, only when the first due
event actually needs inference.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
import traceback
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Optional

from . import contract, live_event
from .config import Config, in_training_domain
from .sources import (FnetMtSource, MultiSource, UsgsSource, candidate_depth, candidate_id,
                      candidate_latlon, candidate_time, is_provisional_candidate)
from .state import (DATA_WAITING, FAILED, INFERRED, OUT_OF_DOMAIN, PENDING, PUBLISHED,
                    SUPERSEDED, State)
from .store import FileStore, GitBranchStore
from .util import from_iso, to_iso, utcnow


# --------------------------------------------------------------------------- helpers
def _default_backend_factory():
    """Construct the NpeBackend singleton from the env (lazy: imports torch/seismo_sbi)."""
    from .npe_backend import NpeBackend

    cfg_path = os.environ.get("FNET_CONFIG", live_event.DEFAULT_CONFIG)
    ckpt = os.environ.get("FNET_CKPT", live_event.DEFAULT_CKPT)
    n = os.environ.get("FNET_NSAMPLES")
    kw = {"num_samples": int(n)} if n else {}
    return NpeBackend(cfg_path, ckpt, **kw)


def _has_waveforms(raw) -> bool:
    """True iff `raw` is a real dir holding at least one file (the download seam's result)."""
    if not raw:
        return False
    p = Path(raw)
    if not p.exists():
        return False
    return any(f.is_file() for f in p.rglob("*"))


def _reset_dir(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)


def _retry_waiting(state: State, eid: str, now, error: str) -> str:
    """Bump the retry counter; go `data_waiting` unless the attempt cap made it `failed`."""
    st = state.schedule_retry(eid, now, error=error)
    if st.status != FAILED:
        st.status = DATA_WAITING
    return st.status


def _status_hist(state: State) -> dict:
    hist: dict = {}
    for st in state.events.values():
        hist[st.status] = hist.get(st.status, 0) + 1
    return hist


# ----------------------------------------------------------- provisional / supersede
# Space-time matching tolerances between a provisional USGS event and an F-net solution
# (same values as `fnet_mt.match_event`).
_MATCH_TOL_SEC = 120.0
_MATCH_TOL_DEG = 1.0


def _event_origin_time(eid: str, st) -> Optional[datetime]:
    """Origin time of a state entry: the stamped `origin_time`, else parsed from a legacy
    `fnet_<YYYYMMDDTHHMMSS>` id (entries that predate the metadata fields)."""
    if st.origin_time:
        return from_iso(st.origin_time)
    if eid.startswith("fnet_"):
        try:
            return datetime.strptime(eid[5:], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _spacetime_match(t_a, lat_a, lon_a, t_b, lat_b, lon_b) -> bool:
    """Same physical event? Origin times within `_MATCH_TOL_SEC` AND epicentres within
    `_MATCH_TOL_DEG` (time-only when either side lacks coordinates)."""
    from .fnet_mt import _haversine_deg

    if t_a is None or t_b is None:
        return False
    if abs((t_a - t_b).total_seconds()) > _MATCH_TOL_SEC:
        return False
    if lat_a is None or lon_a is None or lat_b is None or lon_b is None:
        return True
    return _haversine_deg(lat_a, lon_a, lat_b, lon_b) <= _MATCH_TOL_DEG


def _resolve_supersedes(state: State, store, by_id: dict, now) -> None:
    """Link every provisional (USGS-discovered) event to a matching F-net event, then retire it.

    Two match paths per provisional event: (a) this tick's F-net candidates (also covers both
    sources returning the same event in one tick — F-net wins), then (b) F-net events already
    in the state (the F-net solution was processed earlier / fell out of the poll window).
    On a match the provisional id goes terminal `superseded` (alias `superseded_by`), is
    removed from this tick's work, and its published record — if any — is deleted once the
    replacing F-net event is terminal (otherwise the due-loop deletes it on F-net success).
    """
    fnet_cands = [(cid, c) for cid, c in by_id.items() if not is_provisional_candidate(c)]
    for uid, ust in list(state.events.items()):
        if not ust.provisional or ust.status in (SUPERSEDED, OUT_OF_DOMAIN):
            continue
        u_t = _event_origin_time(uid, ust)
        fid = None
        for cid, cand in fnet_cands:  # (a) same/any-tick F-net candidate
            c_lat, c_lon = candidate_latlon(cand)
            if cid != uid and _spacetime_match(u_t, ust.lat, ust.lon,
                                               candidate_time(cand), c_lat, c_lon):
                fid = cid
                break
        if fid is None:  # (b) F-net event known to the state but not in this poll
            for cid, cst in state.events.items():
                if cst.provisional or cid == uid:
                    continue
                if _spacetime_match(u_t, ust.lat, ust.lon,
                                    _event_origin_time(cid, cst), cst.lat, cst.lon):
                    fid = cid
                    break
        if fid is None:
            continue
        had_record = ust.status in (INFERRED, PUBLISHED)
        state.mark_superseded(uid, fid, now)
        by_id.pop(uid, None)
        fst = state.events.get(fid)
        if had_record and fst is not None and fst.terminal:
            # the replacement is already resolved (published earlier, or out-of-domain):
            # drop the provisional record now — nothing will replace it later.
            store.delete(uid)
        print(f"[supersede] {uid} -> {fid}: F-net solution matches the provisional USGS "
              f"event (single record kept under the F-net id).", flush=True)


# --------------------------------------------------------------------------- one tick
def tick(
    out_dir,
    source,
    store,
    *,
    cfg: Optional[Config] = None,
    now: Optional[datetime] = None,
    state: Optional[State] = None,
    backend_factory=None,
    delay_minutes: Optional[int] = None,
    n_samples: int = 2000,
    qa: bool = True,
    publish: bool = False,
) -> dict:
    """Advance every due event by one step, persist the store + state, and return a summary.

    Seams (all monkeypatched in the offline tests): `source.fetch`, the module-level
    `live_event.download_event_waveforms` / `build_event_h5` / `infer_live_event`, `store.*`,
    and `backend_factory` (called at most once per tick, only when a download yields data).
    """
    cfg = cfg or Config()
    now = now or utcnow()
    out_dir = Path(out_dir)
    state_path = out_dir / "state.json"
    if state is None:
        state = State.load(str(state_path))
    delay = timedelta(minutes=cfg.delay_minutes if delay_minutes is None else delay_minutes)
    backend_factory = backend_factory or _default_backend_factory

    # 1. poll -> candidates, keyed by stable id (the source lookback must already span the
    #    oldest non-terminal event so earlier-run events re-resolve here; see `build_source`).
    candidates = source.fetch(now)
    by_id = {candidate_id(c): c for c in candidates}
    cat_times = [candidate_time(c) for c in candidates]

    # 2. register each candidate; hold back ones younger than the archive-lag delay window.
    #    Out-of-training-domain candidates (epicentre outside the main-arc prior box, in the
    #    Izu–Bonin exclusion strip, or too deep) are recognised HERE and made terminal before
    #    the due-loop, so they are never downloaded/retried/published (env FNET_MAX_DEPTH_KM
    #    overrides the depth cut).
    max_depth_km = float(os.environ.get("FNET_MAX_DEPTH_KM") or cfg.max_depth_km)
    for cid, cand in by_id.items():
        lat, lon = candidate_latlon(cand)
        st = state.register(cid, now, origin_time=to_iso(candidate_time(cand)), lat=lat,
                            lon=lon, provisional=is_provisional_candidate(cand))
        if st.terminal:
            continue
        ok, reason = in_training_domain(lat, lon, candidate_depth(cand),
                                        max_depth_km=max_depth_km)
        if not ok:
            state.mark_out_of_domain(cid, now, error=reason)
            print(f"[out-of-domain] {cid}: {reason} — skipped (no download/retry).",
                  flush=True)
            continue
        if st.status == PENDING and st.attempts == 0 and (now - candidate_time(cand)) < delay:
            # too young to have reached the F-net archive: leave pending, mature later.
            st.next_retry_at = to_iso(candidate_time(cand) + delay)

    # 2b. retire provisional (USGS) events whose F-net solution has arrived — the standard
    #     F-net path replaces the pending-reference record under the F-net id.
    _resolve_supersedes(state, store, by_id, now)

    # 3. drive each due event one full step this tick.
    backend = None
    inferred_ids = []
    counts = {"due": 0, "inferred": 0, "data_waiting": 0, "failed": 0, "unresolved": 0}
    for eid in state.due(now):
        counts["due"] += 1
        sol = by_id.get(eid)
        if sol is None:
            # lookback gap: the source window didn't return this event's solution this tick.
            # Schedule a retry so it isn't perpetually "due" (would spin --exit-when-drained).
            _retry_waiting(state, eid, now, "solution not in source lookback window")
            counts["unresolved"] += 1
            continue
        work_dir = out_dir / "_work" / eid
        try:
            _reset_dir(work_dir)
            raw = live_event.download_event_waveforms(sol, work_dir)
            if not _has_waveforms(raw):
                _retry_waiting(state, eid, now, "no waveforms downloaded (archive lag?)")
                counts["data_waiting"] += 1
                continue
            if backend is None:
                backend = backend_factory()
            event_h5 = live_event.build_event_h5(sol, work_dir, backend)
            if event_h5 is None:
                _retry_waiting(state, eid, now, "h5 build returned None (insufficient stations)")
                counts["data_waiting"] += 1
                continue
            ev, post, _samples6, _qa_res, _present = live_event.infer_live_event(
                sol, event_h5, backend, n=n_samples, qa=qa, qa_full=qa,
                catalogue_times=cat_times)
            rec = contract.build_event_record(
                ev, post, to_iso(now), mock=False, model="seismo_sbi-npe-live")
            store.upsert(rec)
            state.advance(eid, INFERRED, now)
            # a successful F-net record replaces any provisional (USGS) record it superseded
            for uid, ust in state.events.items():
                if ust.status == SUPERSEDED and ust.superseded_by == eid:
                    store.delete(uid)
            inferred_ids.append(eid)
            counts["inferred"] += 1
            shutil.rmtree(work_dir, ignore_errors=True)  # keep only on failure (below)
        except Exception as e:  # noqa: BLE001 — one bad event must not kill the tick
            traceback.print_exc()
            status = _retry_waiting(state, eid, now, f"{type(e).__name__}: {e}")
            counts["failed" if status == FAILED else "data_waiting"] += 1
            # work_dir intentionally left in place for debugging.

    # 4. rebuild the index over everything persisted so far.
    try:
        store.write_index(now=now)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    # 5. resolve publication (see the module docstring's convention).
    if inferred_ids:
        published_ok = True
        if publish:
            try:
                store.publish()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                published_ok = False
        if published_ok:
            for eid in inferred_ids:
                state.advance(eid, PUBLISHED, now)

    state.save(str(state_path))

    due_remaining = state.due(now)
    summary = {
        "now": to_iso(now),
        "counts": counts,
        "status_hist": _status_hist(state),
        "due_remaining": due_remaining,
        "n_candidates": len(candidates),
        "published": bool(inferred_ids),
    }
    print(
        f"[tick {summary['now']}] candidates={summary['n_candidates']} due={counts['due']} "
        f"inferred={counts['inferred']} data_waiting={counts['data_waiting']} "
        f"failed={counts['failed']} unresolved={counts['unresolved']} "
        f"| states={summary['status_hist']} due_remaining={len(due_remaining)}",
        flush=True,
    )
    return summary


# --------------------------------------------------------------------------- wiring
def build_source(cfg: Config, state: State, now: datetime, backfill_start: Optional[datetime],
                 min_mw: Optional[float] = None):
    """The live two-source poll: the F-net MT catalogue (authoritative, days–weeks late) plus
    the USGS FDSN feed (near-live discovery, provisional pending-reference records) when
    `cfg.usgs_enabled`.  The shared lookback spans the rolling window, any `backfill_start`,
    AND the oldest still-non-terminal event (so earlier-run events re-resolve to their
    solution).  F-net is listed first so same-tick duplicates resolve in its favour."""
    start = now - timedelta(days=cfg.window_days)
    if backfill_start is not None and backfill_start < start:
        start = backfill_start
    for st in state.events.values():
        if not st.terminal and st.first_seen:
            fs = from_iso(st.first_seen)
            if fs < start:
                start = fs
    # +2 days of margin so an event near the window edge is comfortably inside the query.
    lookback_days = max(1, ceil((now - start).total_seconds() / 86400.0) + 2)
    fnet = FnetMtSource(cfg, lookback_days=lookback_days, min_mw=min_mw)
    if not cfg.usgs_enabled:
        return fnet
    usgs = UsgsSource(cfg, min_magnitude=cfg.usgs_min_magnitude, lookback_days=lookback_days)
    return MultiSource(fnet, usgs)


def _build_store(out_dir: str, publish: bool):
    if publish:
        return GitBranchStore(
            out_dir,
            enable_push=True,
            token=os.environ.get("GITHUB_TOKEN"),
            remote=os.environ.get("GITHUB_REPOSITORY"),
        )
    return FileStore(out_dir)


def run_once(
    out_dir: str,
    *,
    cfg: Optional[Config] = None,
    now: Optional[datetime] = None,
    backfill_start: Optional[datetime] = None,
    publish: bool = False,
    qa: bool = True,
    n_samples: int = 2000,
    min_mw: Optional[float] = None,
) -> dict:
    """Build the live source + store from the env and run exactly one tick."""
    cfg = cfg or Config()
    now = now or utcnow()
    state = State.load(os.path.join(out_dir, "state.json"))
    source = build_source(cfg, state, now, backfill_start, min_mw)
    store = _build_store(out_dir, publish)
    return tick(out_dir, source, store, cfg=cfg, now=now, state=state,
                publish=publish, qa=qa, n_samples=n_samples)


# --------------------------------------------------------------------------- CLI
def _parse_when(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date/datetime as UTC (a naive string is TREATED as UTC, never local)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _report_drained(summary: dict) -> None:
    waiting = summary["status_hist"].get(DATA_WAITING, 0)
    pending = summary["status_hist"].get(PENDING, 0)
    print(
        f"[drained] no event due now; exiting. leftover future-scheduled work: "
        f"pending={pending} data_waiting={waiting} "
        f"(published={summary['status_hist'].get(PUBLISHED, 0)} "
        f"failed={summary['status_hist'].get(FAILED, 0)}).",
        flush=True,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Live F-net NPE monitor — one supervised state-machine tick (or a loop).")
    ap.add_argument("--out", required=True, help="store dir; state persists at <out>/state.json")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="run ONE tick then exit (default; what the CI cron runs)")
    mode.add_argument("--loop", action="store_true",
                      help="local daemon: a tick every --interval seconds")
    ap.add_argument("--interval", type=int, default=1200, help="loop tick interval (s)")
    ap.add_argument("--backfill-start", default=os.environ.get("BACKFILL_START") or None,
                    help="ISO date widening the poll-window start (env BACKFILL_START; CLI wins)")
    ap.add_argument("--exit-when-drained", action="store_true",
                    help="(with --loop) exit once no event is due now (future retries are OK)")
    ap.add_argument("--publish", action="store_true",
                    help="wrap the store in GitBranchStore + publish() after a changed tick "
                         "(default OFF; in CI the workflow git-push publishes instead)")
    ap.add_argument("--no-qa", action="store_true", help="disable the FULL QA suite")
    ap.add_argument("--min-mw", type=float, default=None, help="override Config.min_magnitude")
    args = ap.parse_args(argv)

    cfg = Config()
    qa = not args.no_qa
    n_samples = int(os.environ.get("FNET_NSAMPLES") or 2000)
    backfill_start = _parse_when(args.backfill_start)

    def _one() -> dict:
        return run_once(args.out, cfg=cfg, backfill_start=backfill_start, publish=args.publish,
                        qa=qa, n_samples=n_samples, min_mw=args.min_mw)

    if not args.loop:  # --once (default)
        _one()
        return 0

    while True:  # --loop: per-tick try/except so one bad tick never kills the loop.
        try:
            summary = _one()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            summary = None
        if args.exit_when_drained and summary is not None and not summary["due_remaining"]:
            _report_drained(summary)
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
