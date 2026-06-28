"""Parse a QuakeML event catalogue into the worker's `QuakeEvent` shape.

Network-free; needs obspy (lives in the `seismo-sbi` conda env). This is the STATIC
counterpart to `catalogue.poll` — the live worker swaps `parse_quakeml` for `poll` with no
downstream change. Used by the realistic demo generator (`build_demo_catalogue`) to read
`/data/alex/fnet_japan/events_jan2026.xml` (78 USGS-sourced Japan events, Jan 2026).
"""

from __future__ import annotations

import re
from datetime import timezone
from typing import List

from .catalogue import QuakeEvent

_EVENTID = re.compile(r"eventid=([^&]+)")


def usgs_id(resource_id: str) -> str:
    """Extract the USGS event id (e.g. `us7000rrdp`) from a QuakeML resource id like
    `quakeml:earthquake.usgs.gov/fdsnws/event/1/query?eventid=us7000rrdp&format=quakeml`.
    Falls back to the last path/segment token if no `eventid=` is present."""
    m = _EVENTID.search(resource_id)
    if m:
        return m.group(1)
    tail = resource_id.rstrip("/").split("/")[-1]
    return tail or resource_id


def parse_quakeml(path: str) -> List[QuakeEvent]:
    import obspy

    cat = obspy.read_events(path)
    out: List[QuakeEvent] = []
    for e in cat:
        o = e.preferred_origin() or (e.origins[0] if e.origins else None)
        m = e.preferred_magnitude() or (e.magnitudes[0] if e.magnitudes else None)
        if o is None or o.latitude is None or o.longitude is None:
            continue
        region = e.event_descriptions[0].text if e.event_descriptions else "Japan region"
        depth_km = float(o.depth) / 1000.0 if o.depth is not None else 0.0
        out.append(
            QuakeEvent(
                id=usgs_id(str(e.resource_id)),
                time=o.time.datetime.replace(tzinfo=timezone.utc),
                lon=float(o.longitude),
                lat=float(o.latitude),
                depth_km=depth_km,
                mag=float(m.mag) if m is not None and m.mag is not None else 0.0,
                magtype=str(m.magnitude_type) if m is not None and m.magnitude_type else "M",
                region=region,
            )
        )
    return out
