import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from fnet_monitor import contract
from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.inference import mock_posterior
from fnet_monitor.store import FileStore, GitBranchStore, MemoryStore

NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def _rec(eid, days_ago=1):
    ev = QuakeEvent(id=eid, time=NOW - timedelta(days=days_ago), lon=140.0, lat=36.0,
                    depth_km=30.0, mag=4.8, magtype="Mw", region="R")
    return contract.build_event_record(ev, mock_posterior(ev, 20), "2026-06-28T00:00:00Z", True)


# --------------------------------------------------------------------------- MemoryStore
def test_memorystore_validates_on_upsert():
    store = MemoryStore()
    bad = _rec("bad")
    bad["posterior"]["gamma"][0] = 99.0  # contract violation (lune bound)
    with pytest.raises(AssertionError):
        store.upsert(bad)
    assert store.read_records() == []
    # an EMPTY references list is NOT a violation (pending F-net reference, Phase 8)
    pending = _rec("pending")
    pending["references"] = []
    store.upsert(pending)
    assert len(store.read_records()) == 1


def test_store_delete_removes_record(tmp_path):
    fs = FileStore(str(tmp_path))
    fs.upsert(_rec("a"))
    fs.delete("a")
    fs.delete("a")  # idempotent no-op
    assert fs.read_records() == []
    ms = MemoryStore()
    ms.upsert(_rec("a"))
    ms.delete("a")
    ms.delete("missing")
    assert ms.read_records() == []


def test_memorystore_upsert_is_idempotent_by_id():
    store = MemoryStore()
    store.upsert(_rec("x"))
    store.upsert(_rec("x"))
    assert len(store.read_records()) == 1


# --------------------------------------------------------------------------- FileStore
def test_filestore_roundtrip_no_prune(tmp_path):
    store = FileStore(str(tmp_path))
    store.upsert(_rec("a", days_ago=1))
    store.upsert(_rec("b", days_ago=2))
    recs = store.read_records()
    assert len(recs) == 2
    index = store.write_index(recs, now=NOW, mock=True)
    contract.validate_index(index)
    assert len(index["features"]) == 2
    assert os.path.exists(os.path.join(str(tmp_path), "events.json"))
    for feat in index["features"]:
        assert os.path.exists(os.path.join(str(tmp_path), feat["properties"]["ensemble"]))


def test_filestore_write_index_reads_disk_when_records_omitted(tmp_path):
    store = FileStore(str(tmp_path))
    store.upsert(_rec("a"))
    index = store.write_index(now=NOW, mock=True)  # records=None -> read from disk
    assert len(index["features"]) == 1


def test_filestore_prune_drops_aged_out_events(tmp_path):
    store = FileStore(str(tmp_path), prune=True)
    store.upsert(_rec("recent", days_ago=1))
    store.upsert(_rec("old", days_ago=40))  # outside the 30-day window
    index = store.write_index(now=NOW, mock=True)
    ids = [f["properties"]["id"] for f in index["features"]]
    assert ids == ["recent"]
    # rolling-window retention deletes the aged-out file
    assert not os.path.exists(os.path.join(str(tmp_path), "events", "old.json"))


def test_filestore_publish_is_noop(tmp_path):
    assert FileStore(str(tmp_path)).publish() is None


# --------------------------------------------------------------------------- GitBranchStore guard
def test_gitbranchstore_publish_noop_when_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("fnet_monitor.store.subprocess.run",
                        lambda *a, **k: calls.append(a))
    store = GitBranchStore(str(tmp_path), enable_push=False, token="t", remote="o/r")
    store.upsert(_rec("a"))
    store.write_index(now=NOW, mock=True)
    store.publish()
    assert calls == []  # nothing ran
    assert store.push_enabled is False


def test_gitbranchstore_publish_noop_without_token_or_remote(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("fnet_monitor.store.subprocess.run",
                        lambda *a, **k: calls.append(a))
    # enabled but missing token
    GitBranchStore(str(tmp_path), enable_push=True, remote="o/r").publish()
    # enabled but missing remote
    GitBranchStore(str(tmp_path), enable_push=True, token="t").publish()
    assert calls == []


def test_gitbranchstore_publish_runs_when_enabled(tmp_path, monkeypatch):
    calls = []

    class _Res:
        returncode = 0

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return _Res()

    monkeypatch.setattr("fnet_monitor.store.subprocess.run", fake_run)
    store = GitBranchStore(str(tmp_path), enable_push=True, token="SECRET", remote="owner/repo")
    store.upsert(_rec("a"))
    store.write_index(now=NOW, mock=True)
    assert store.push_enabled is True
    store.publish()
    # git init/config/add/commit/push all ran
    verbs = [c[1] for c in calls if c and c[0] == "git"]
    assert "init" in verbs and "add" in verbs and "commit" in verbs and "push" in verbs
    # the token appears ONLY in the push URL, injected as x-access-token
    push = next(c for c in calls if c[:2] == ["git", "push"])
    assert any("x-access-token:SECRET@github.com/owner/repo.git" in tok for tok in push)
