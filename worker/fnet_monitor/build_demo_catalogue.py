"""Build the realistic STATIC demo data store from the real Jan-2026 Japan catalogue.

  conda run -n seismo-sbi python -m fnet_monitor.build_demo_catalogue \
      --xml /data/alex/fnet_japan/events_jan2026.xml --out ../public/demo

Reads the QuakeML (78 USGS Japan events) → attaches hybrid-real reference MTs (from the committed
cache; synthesizes a plausible fallback where none exist) → generates a dummy Mw-scaled posterior
per event → writes the schema-3 contract artefacts (`events.json` + `events/<id>.json`),
overwriting the curated mock fixtures. DETERMINISTIC + offline (reads only the reference cache).

This is the static realistic path; the eventual live worker stays `run.py`, swapping
`parse_quakeml`→`catalogue.poll`, the cache→`references.fetch_references`,
`synthetic.synthetic_posterior`→`inference.real_posterior` — the contract + frontend are identical.
"""

from __future__ import annotations

import argparse
import glob
import os
from collections import Counter
from typing import List, Optional

from . import contract, references, synthetic
from .config import Config
from .quakeml import parse_quakeml
from .util import to_iso, utcnow

DEFAULT_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "reference_cache.json")


def _event_refs(ev, raw_refs: List[dict]) -> List[dict]:
    """Normalise real refs (sorted, primary = most trusted); synthesize a fallback if none."""
    if raw_refs:
        normed = [references.normalise_reference(r) for r in raw_refs]
        normed.sort(key=lambda r: references.source_rank(r["source"]))
        return normed
    return [references.normalise_reference(references.synthesize_reference(ev))]


def build(
    xml_path: str,
    out_dir: str,
    cache_path: str,
    *,
    seed: int = 0,
    n_cloud: int = 250,
    n_mt6: int = 80,
    clean: bool = True,
) -> dict:
    events = parse_quakeml(xml_path)
    cache = references.load_cache(cache_path)
    generated = to_iso(utcnow())

    if clean:
        for p in glob.glob(os.path.join(out_dir, "events", "*.json")):
            os.remove(p)

    records: List[dict] = []
    coverage: Counter = Counter()
    for ev in events:
        refs = _event_refs(ev, cache.get(ev.id, []))
        coverage[refs[0]["source"]] += 1
        coverage["n_refs_total"] += len(refs)
        ev_seed = seed ^ references._seed(ev.id)
        post = synthetic.synthetic_posterior(ev, refs, n_cloud=n_cloud, n_mt6=n_mt6, seed=ev_seed)
        rec = contract.build_event_record(ev, post, generated, mock=True, model="synthetic-demo")
        contract.validate_event(rec)
        contract.write_event(out_dir, rec)
        records.append(rec)

    index = contract.build_static_index(records, generated, Config(), mock=True)
    contract.validate_index(index)
    contract.write_index(out_dir, index)

    real = sum(coverage[s] for s in ("GCMT", "USGS", "F-net"))
    print(f"built {len(records)} events -> {out_dir}")
    print(
        "  primary-reference coverage: "
        + ", ".join(f"{s}={coverage[s]}" for s in ("GCMT", "USGS", "F-net", "synthetic") if coverage[s])
        + f"  (real {real}/{len(records)} = {100*real/max(1,len(records)):.0f}%)"
    )
    return index


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the realistic static demo catalogue.")
    ap.add_argument("--xml", default="/data/alex/fnet_japan/events_jan2026.xml")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "..", "public", "demo"))
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-cloud", type=int, default=250)
    ap.add_argument("--n-mt6", type=int, default=80)
    ap.add_argument("--no-clean", action="store_true", help="keep existing events/*.json")
    args = ap.parse_args(argv)
    build(
        args.xml,
        os.path.normpath(args.out),
        os.path.normpath(args.cache),
        seed=args.seed,
        n_cloud=args.n_cloud,
        n_mt6=args.n_mt6,
        clean=not args.no_clean,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
