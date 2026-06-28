from datetime import timezone

import pytest

obspy = pytest.importorskip("obspy")

from obspy import UTCDateTime  # noqa: E402
from obspy.core.event import (  # noqa: E402
    Catalog,
    Event,
    EventDescription,
    Magnitude,
    Origin,
    ResourceIdentifier,
)

from fnet_monitor.quakeml import parse_quakeml, usgs_id  # noqa: E402


def test_usgs_id():
    assert (
        usgs_id("quakeml:earthquake.usgs.gov/fdsnws/event/1/query?eventid=us7000rrdp&format=quakeml")
        == "us7000rrdp"
    )
    assert usgs_id("quakeml:smi.local/x/y/abc") == "abc"


def test_parse_quakeml(tmp_path):
    ev = Event(resource_id=ResourceIdentifier(id="quakeml:foo/query?eventid=us123&format=quakeml"))
    o = Origin(time=UTCDateTime("2026-01-05T01:02:03"), latitude=37.0, longitude=140.0, depth=44371.0)
    ev.origins = [o]
    ev.preferred_origin_id = o.resource_id
    m = Magnitude(mag=4.6, magnitude_type="mb")
    ev.magnitudes = [m]
    ev.preferred_magnitude_id = m.resource_id
    ev.event_descriptions = [EventDescription(text="Off Honshu, Japan")]
    p = tmp_path / "e.xml"
    Catalog(events=[ev]).write(str(p), format="QUAKEML")

    out = parse_quakeml(str(p))
    assert len(out) == 1
    q = out[0]
    assert q.id == "us123"
    assert abs(q.depth_km - 44.371) < 1e-6  # metres -> km
    assert q.mag == 4.6 and q.magtype == "mb"
    assert q.region == "Off Honshu, Japan"
    assert q.lat == 37.0 and q.lon == 140.0
    assert q.time.tzinfo == timezone.utc
