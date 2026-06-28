from fnet_monitor.state import State


def test_roundtrip(tmp_path):
    s = State(last_time="2026-06-01T00:00:00Z", processed_ids=["a", "b"])
    p = tmp_path / "state.json"
    s.save(str(p))
    s2 = State.load(str(p))
    assert s2.last_time == "2026-06-01T00:00:00Z"
    assert s2.processed_ids == ["a", "b"]
    assert s2.updated  # stamped on save


def test_remember_caps_and_dedups():
    s = State()
    for i in range(10):
        s.remember(f"id{i}", max_ids=5)
    assert len(s.processed_ids) == 5
    assert s.processed_ids[0] == "id5"
    s.remember("id9", max_ids=5)  # already present
    assert s.processed_ids.count("id9") == 1


def test_load_missing(tmp_path):
    assert State.load(str(tmp_path / "nope.json")).last_time is None
