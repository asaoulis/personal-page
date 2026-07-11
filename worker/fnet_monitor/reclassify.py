"""Store maintenance — reclassify an existing store against the model's training domain,
and (optionally) recompute the probabilistic source-type block on every record.

The live monitor now filters candidates to the NPE's TRAINING PRIOR domain
(`config.in_training_domain`: main-arc box, Izu–Bonin exclusion, depth <= 80 km), but stores
built before that filter still carry out-of-domain events with garbage posteriors.  This CLI
walks an existing store's records + `state.json`, marks the now-OOD events terminal
`out_of_domain`, moves their record JSONs to `<store>/_excluded/`, and rebuilds the index over
the surviving in-domain set:

    python -m fnet_monitor.reclassify --out /data/alex/fnet_live/store
    python -m fnet_monitor.reclassify --out <store> --dry-run       # report only, change nothing
    python -m fnet_monitor.reclassify --out <store> --source-type   # + refresh source_type blocks

`--source-type` recomputes each surviving record's `source_type`
(`{p_outside_dc_box_10, label}`, see `source_type.py`) from its stored posterior
(gamma, delta) cloud — used to migrate stores written before the probabilistic block existed.

Always prints a summary: excluded count (with reasons), surviving count, and the
Kagan-vs-F-net median over the surviving in-domain records.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import statistics
from typing import List, Optional, Tuple

from .config import Config, in_training_domain
from .state import State
from .store import FileStore
from .util import utcnow


def _load_records(out_dir: str) -> List[Tuple[str, dict]]:
    out = []
    for path in sorted(glob.glob(os.path.join(out_dir, "events", "*.json"))):
        with open(path) as f:
            out.append((path, json.load(f)))
    return out


def _primary_fnet_kagan(rec: dict) -> Optional[float]:
    """Kagan angle (deg) of the model best vs the primary F-net reference, if present."""
    for ref in rec.get("references") or []:
        if "f-net" in str(ref.get("source", "")).lower():
            kg = ref.get("kagan_deg")
            return float(kg) if kg is not None else None
    return None


def reclassify_domain(out_dir: str, *, max_depth_km: Optional[float] = None,
                      dry_run: bool = False, refresh_source_type: bool = False,
                      now=None) -> dict:
    """Apply the training-domain filter to an existing store.  Returns a summary dict.

    Moves OOD record files to `<out_dir>/_excluded/`, marks their ids `out_of_domain` in
    `state.json`, optionally refreshes `source_type` on the survivors, rebuilds the index.
    """
    cfg = Config()
    now = now or utcnow()
    max_depth = float(os.environ.get("FNET_MAX_DEPTH_KM") or
                      (max_depth_km if max_depth_km is not None else cfg.max_depth_km))
    state_path = os.path.join(out_dir, "state.json")
    state = State.load(state_path)

    excluded, kept = [], []
    for path, rec in _load_records(out_dir):
        ok, reason = in_training_domain(rec.get("lat"), rec.get("lon"), rec.get("depth_km"),
                                        max_depth_km=max_depth)
        if ok:
            kept.append((path, rec))
            continue
        excluded.append({"id": rec["id"], "reason": reason})
        print(f"[exclude] {rec['id']}: {reason}", flush=True)
        if dry_run:
            continue
        state.mark_out_of_domain(rec["id"], now, error=reason)
        excl_dir = os.path.join(out_dir, "_excluded")
        os.makedirs(excl_dir, exist_ok=True)
        shutil.move(path, os.path.join(excl_dir, os.path.basename(path)))

    if refresh_source_type and not dry_run:
        from .source_type import source_type_block
        for path, rec in kept:
            post = rec.get("posterior") or {}
            rec["source_type"] = source_type_block(gamma=post.get("gamma"),
                                                   delta=post.get("delta"))
            rec["p_outside_dc_box"] = rec["source_type"]["p_outside_dc_box_10"]
            with open(path, "w") as f:
                json.dump(rec, f, separators=(",", ":"))

    if not dry_run:
        FileStore(out_dir, cfg).write_index(now=now)
        state.save(state_path)

    kagans = [k for _, r in kept if (k := _primary_fnet_kagan(r)) is not None]
    summary = {
        "n_records": len(kept) + len(excluded),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "n_kept": len(kept),
        "kagan_median_deg": round(statistics.median(kagans), 2) if kagans else None,
        "n_kagan": len(kagans),
        "dry_run": dry_run,
    }
    print(f"[reclassify] {summary['n_excluded']} excluded / {summary['n_kept']} kept "
          f"(of {summary['n_records']}); Kagan-vs-F-net median of survivors: "
          f"{summary['kagan_median_deg']}° over {summary['n_kagan']} refs"
          f"{' [DRY RUN — nothing written]' if dry_run else ''}", flush=True)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Reclassify an existing store against the NPE training domain.")
    ap.add_argument("--out", required=True, help="store dir (holds events/ + state.json)")
    ap.add_argument("--max-depth-km", type=float, default=None,
                    help="override the depth cut (default Config/FNET_MAX_DEPTH_KM)")
    ap.add_argument("--dry-run", action="store_true", help="report only; move/write nothing")
    ap.add_argument("--source-type", action="store_true",
                    help="also recompute the probabilistic source_type block on survivors")
    args = ap.parse_args(argv)
    reclassify_domain(args.out, max_depth_km=args.max_depth_km, dry_run=args.dry_run,
                      refresh_source_type=args.source_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
