"""Worker entrypoint — poll → infer (mock) → write the v2 contract → save state.

  python -m fnet_monitor.run --out ../public/demo --source demo     # regenerate demo data
  python -m fnet_monitor.run --out <dir>                            # live USGS poll (mock infer)

Real NPE inference (M-D2) is selected with --real once the model is wired in.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Callable, List, Optional

from . import catalogue, contract, demo, inference
from .config import Config
from .state import State
from .util import from_iso, to_iso, utcnow

Provider = Callable[[Config, State, datetime], List["catalogue.QuakeEvent"]]


def _usgs_provider(cfg: Config, state: State, now: datetime) -> List["catalogue.QuakeEvent"]:
    return catalogue.poll(cfg, state, now, catalogue.usgs_fetcher)


def run(
    out_dir: str,
    *,
    mock: bool = True,
    now: Optional[datetime] = None,
    provider: Optional[Provider] = None,
    cfg: Optional[Config] = None,
) -> dict:
    cfg = cfg or Config()
    now = now or utcnow()
    provider = provider or _usgs_provider
    state_path = os.path.join(out_dir, "state.json")
    state = State.load(state_path)
    generated = to_iso(now)

    events = provider(cfg, state, now)
    for ev in events:
        post = (
            inference.mock_posterior(ev, cfg.n_samples)
            if mock
            else inference.real_posterior(ev, cfg.n_samples)
        )
        rec = contract.build_event_record(ev, post, generated, mock)
        contract.validate_event(rec)
        contract.write_event(out_dir, rec)
        state.remember(ev.id, cfg.max_processed_ids)
        if state.last_time is None or ev.time > from_iso(state.last_time):
            state.last_time = to_iso(ev.time)

    index = contract.rebuild_index(out_dir, cfg, now, mock)
    contract.validate_index(index)
    contract.write_index(out_dir, index)
    state.save(state_path)
    return index


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="F-net inference worker (skeleton).")
    ap.add_argument("--out", required=True, help="output directory for the results store")
    ap.add_argument(
        "--source",
        choices=["usgs", "demo"],
        default="usgs",
        help="event source: live USGS FDSN poll, or the curated demo catalogue",
    )
    ap.add_argument("--real", action="store_true", help="use real NPE inference (M-D2; not yet implemented)")
    ap.add_argument("--now", default=None, help="override 'now' (ISO, UTC) for deterministic runs")
    args = ap.parse_args(argv)

    now = from_iso(args.now) if args.now else utcnow()
    provider = demo.provider if args.source == "demo" else _usgs_provider
    index = run(args.out, mock=not args.real, now=now, provider=provider)
    print(f"wrote {len(index['features'])} events to {args.out} (source={args.source}, mock={not args.real})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
