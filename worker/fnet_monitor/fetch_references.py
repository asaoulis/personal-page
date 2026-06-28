"""ONE-TIME ONLINE step: fetch real reference moment tensors and write the committed cache.

  conda run -n seismo-sbi python -m fnet_monitor.fetch_references \
      --xml /data/alex/fnet_japan/events_jan2026.xml

Sources, per event (all real; primary order F-net > GCMT > USGS):
  - F-net (NIED) regional MT catalogue — THE Japanese source, ~Mw3.5+ coverage. Queried ONCE for
    the catalogue's time span (`fnet_mt.query_fnet_mt_catalogue`) then matched per event by
    space-time (`fnet_mt.match_event`). See `fnet_mt.py` for the full documented query protocol —
    this is what the LIVE monitor reuses.
  - USGS event-detail endpoint (aggregates US W-phase / GCMT / Duputel moment tensors), per event.

The deterministic generator (`build_demo_catalogue`) reads ONLY the resulting cache
(`worker/data/reference_cache.json`) — separated so generation + tests stay offline/reproducible.
Events with no real solution get a synthetic fallback at generation time.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import timedelta
from typing import List, Optional

from . import references
from .build_demo_catalogue import DEFAULT_CACHE
from .fnet_mt import match_event, query_fnet_mt_catalogue
from .quakeml import parse_quakeml
from .util import to_iso, utcnow


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch real reference MTs (F-net + USGS) -> committed cache.")
    ap.add_argument("--xml", default="/data/alex/fnet_japan/events_jan2026.xml")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--no-fnet", action="store_true", help="skip the F-net catalogue query")
    ap.add_argument("--no-usgs", action="store_true", help="skip the per-event USGS detail fetch")
    args = ap.parse_args(argv)

    events = parse_quakeml(args.xml)

    # 1) F-net: one catalogue query over the event time span (+/- a small pad), then space-time match.
    fnet_sols = []
    if not args.no_fnet and events:
        t0 = min(e.time for e in events) - timedelta(minutes=5)
        t1 = max(e.time for e in events) + timedelta(minutes=5)
        try:
            fnet_sols = query_fnet_mt_catalogue(t0, t1)
            print(f"F-net catalogue: {len(fnet_sols)} solutions in the window")
        except Exception as e:  # noqa: BLE001
            print(f"F-net query FAILED ({type(e).__name__}: {e}); continuing without F-net")

    # 2) per event: F-net match (primary) + USGS detail products.
    cache = {}
    cov: Counter = Counter()
    events_with_any = 0
    for ev in events:
        refs: List[dict] = []
        fn = match_event(ev, fnet_sols) if fnet_sols else None
        if fn is not None:
            refs.append({"source": "F-net", "mt6": fn.m6_use, "mw": fn.mw, "synthetic": False})
        if not args.no_usgs:
            try:
                refs.extend(references.parse_usgs_mt_products(references.usgs_detail_fetcher(ev.id)))
            except Exception:  # noqa: BLE001
                pass
        cache[ev.id] = refs
        if refs:
            events_with_any += 1
        for r in refs:
            cov[r["source"]] += 1

    meta = {
        "fetched": to_iso(utcnow()),
        "n_events": len(events),
        "events_with_real_mt": events_with_any,
        "by_source": dict(cov),
    }
    references.save_cache(os.path.normpath(args.cache), cache, meta=meta)
    print(f"fetched refs for {len(events)} events; {events_with_any} have >=1 real MT")
    print(f"  by source: {dict(cov)}")
    print(f"  wrote {os.path.normpath(args.cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
