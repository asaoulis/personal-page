from datetime import datetime, timedelta, timezone

from fnet_monitor.catalogue import parse_usgs, poll, select_new
from fnet_monitor.config import Config
from fnet_monitor.state import State

NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=timezone.utc)


def _epoch_ms(dt):
    return int(dt.timestamp() * 1000)


def _feat(fid, dt, lat, lon, mag, place="Japan"):
    return {
        "type": "Feature",
        "id": fid,
        "properties": {"mag": mag, "place": place, "time": _epoch_ms(dt), "magType": "mww"},
        "geometry": {"coordinates": [lon, lat, 30.0]},
    }


def _fixture():
    return {
        "type": "FeatureCollection",
        "features": [
            _feat("in_ok", NOW - timedelta(days=2), 36.0, 140.0, 4.5),  # keep
            _feat("too_small", NOW - timedelta(days=2), 36.0, 140.0, 3.0),  # drop: mag
            _feat("outside", NOW - timedelta(days=2), 10.0, 100.0, 5.0),  # drop: bbox
            _feat("too_recent", NOW - timedelta(minutes=10), 36.0, 140.0, 5.0),  # drop: delay
            _feat("too_old", NOW - timedelta(days=40), 36.0, 140.0, 5.0),  # drop: window
        ],
    }


def test_parse_usgs():
    evs = parse_usgs(_fixture())
    assert len(evs) == 5
    e = next(e for e in evs if e.id == "in_ok")
    assert e.lat == 36.0 and e.lon == 140.0 and e.mag == 4.5
    assert e.time.tzinfo is not None  # tz-aware UTC


def test_select_new_filters():
    evs = select_new(parse_usgs(_fixture()), Config(), State(), NOW)
    assert [e.id for e in evs] == ["in_ok"]


def test_select_new_dedups():
    st = State(processed_ids=["in_ok"])
    assert select_new(parse_usgs(_fixture()), Config(), st, NOW) == []


def test_poll_passes_query_and_filters():
    cfg = Config()
    captured = {}

    def fake(url, params):
        captured["url"] = url
        captured["params"] = params
        return _fixture()

    evs = poll(cfg, State(), NOW, fetcher=fake)
    assert [e.id for e in evs] == ["in_ok"]
    assert captured["url"] == cfg.fdsn_url
    assert captured["params"]["minmagnitude"] == cfg.min_magnitude
    assert captured["params"]["minlatitude"] == cfg.bbox["minlat"]
