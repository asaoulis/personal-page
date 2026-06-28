import json
import os
from datetime import datetime, timedelta, timezone

from fnet_monitor import contract, demo, run

NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def test_run_demo_end_to_end(tmp_path):
    out = str(tmp_path)
    index = run.run(out, mock=True, now=NOW, provider=demo.provider)

    assert len(index["features"]) == 8
    contract.validate_index(index)
    assert os.path.exists(os.path.join(out, "events.json"))

    for feat in index["features"]:
        ep = os.path.join(out, feat["properties"]["ensemble"])
        assert os.path.exists(ep)
        with open(ep) as f:
            rec = json.load(f)
        contract.validate_event(rec)

    with open(os.path.join(out, "state.json")) as f:
        st = json.load(f)
    assert len(st["processed_ids"]) == 8
    assert st["last_time"] is not None

    # newest first
    times = [f["properties"]["time"] for f in index["features"]]
    assert times == sorted(times, reverse=True)


def test_run_is_idempotent(tmp_path):
    out = str(tmp_path)
    run.run(out, now=NOW, provider=demo.provider)
    index2 = run.run(out, now=NOW, provider=demo.provider)  # all already processed
    assert len(index2["features"]) == 8  # rebuilt from existing files, no duplicates


def test_rolling_window_prunes(tmp_path):
    out = str(tmp_path)
    run.run(out, now=NOW, provider=demo.provider)
    # 60 days later, every earlier event has aged out of the 30-day window
    index = run.run(out, now=NOW + timedelta(days=60), provider=demo.provider)
    assert len(index["features"]) == 0
    assert not os.listdir(os.path.join(out, "events")) or all(
        not n.endswith(".json") for n in os.listdir(os.path.join(out, "events"))
    )
