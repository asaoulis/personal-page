"""Event stores — the pluggable sink that persists schema-3 records + the index, and (optionally)
publishes them to the `data` branch the frontend reads.

`EventStore` is the seam the monitor writes through:

    upsert(record)          validate + persist ONE per-event record (idempotent by id)
    read_records()          read every persisted record back (to rebuild the index + seed state)
    write_index(records)    (re)build + validate + persist the FeatureCollection index
    publish()               push the store to its published location (a GUARDED no-op by default)

`FileStore` writes the on-disk contract via `contract.*` (default: NO pruning — the index spans the
actual event times; pass `prune=True` for the rolling-window `rebuild_index`).  `MemoryStore` is a
test stub that keeps records in memory and validates each on upsert.  `GitBranchStore` adds the
orphan-`data`-branch force-push recipe from `.github/workflows/update-events.yml` — but `publish()`
NEVER runs unless the store was built with `enable_push=True` AND a token + remote are configured.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
from typing import List, Optional

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore

from . import contract
from .config import Config
from .util import to_iso, utcnow


class EventStore(Protocol):
    def upsert(self, record: dict) -> None:  # pragma: no cover - structural
        ...

    def delete(self, event_id: str) -> None:  # pragma: no cover - structural
        ...

    def read_records(self) -> List[dict]:  # pragma: no cover - structural
        ...

    def write_index(self, records: List[dict]) -> dict:  # pragma: no cover - structural
        ...

    def publish(self) -> None:  # pragma: no cover - structural
        ...


class FileStore:
    """On-disk contract store delegating to `contract.write_event` / `write_index`.

    `prune=False` (default): the index is a static one over the given records with NO now-based
    pruning (window bounds span the real event times).  `prune=True`: use `rebuild_index`, the
    rolling `[now - window_days, now]` retention path that also deletes aged-out event files."""

    def __init__(self, out_dir, cfg: Optional[Config] = None, *, prune: bool = False) -> None:
        self.out_dir = str(out_dir)
        self.cfg = cfg or Config()
        self.prune = prune

    def upsert(self, record: dict) -> None:
        contract.validate_event(record)
        contract.write_event(self.out_dir, record)

    def delete(self, event_id: str) -> None:
        """Remove one per-event record (no-op if absent) — used when a provisional
        (reference-pending) record is superseded by the matching F-net solution."""
        path = os.path.join(self.out_dir, "events", f"{event_id}.json")
        if os.path.exists(path):
            os.remove(path)

    def read_records(self) -> List[dict]:
        recs: List[dict] = []
        for path in sorted(glob.glob(os.path.join(self.out_dir, "events", "*.json"))):
            with open(path) as f:
                recs.append(json.load(f))
        return recs

    def write_index(self, records: Optional[List[dict]] = None, *, now=None, mock: bool = False) -> dict:
        now = now or utcnow()
        if self.prune:
            index = contract.rebuild_index(self.out_dir, self.cfg, now, mock)
        else:
            recs = self.read_records() if records is None else list(records)
            index = contract.build_static_index(recs, to_iso(now), self.cfg, mock)
        contract.validate_index(index)
        contract.write_index(self.out_dir, index)
        return index

    def publish(self) -> None:
        """Local store: nothing to publish."""
        return None


class MemoryStore:
    """In-memory test stub.  Validates every record on upsert; keeps the last-built index."""

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.cfg = cfg or Config()
        self.records: dict = {}  # id -> record
        self.index: Optional[dict] = None

    def upsert(self, record: dict) -> None:
        contract.validate_event(record)
        self.records[record["id"]] = record

    def delete(self, event_id: str) -> None:
        self.records.pop(event_id, None)

    def read_records(self) -> List[dict]:
        return list(self.records.values())

    def write_index(self, records: Optional[List[dict]] = None, *, now=None, mock: bool = False) -> dict:
        recs = self.read_records() if records is None else list(records)
        index = contract.build_static_index(recs, to_iso(now or utcnow()), self.cfg, mock)
        contract.validate_index(index)
        self.index = index
        return index

    def publish(self) -> None:
        return None


class GitBranchStore(FileStore):
    """FileStore that can `publish()` the out-dir as an orphan, force-pushed `data` branch —
    mirroring the recipe in `.github/workflows/update-events.yml`.

    GUARDED: `publish()` is a NO-OP unless the store was constructed with `enable_push=True` AND
    both a `token` and a `remote` are configured.  It never pushes implicitly.
    """

    def __init__(
        self,
        out_dir,
        cfg: Optional[Config] = None,
        *,
        prune: bool = False,
        enable_push: bool = False,
        token: Optional[str] = None,
        remote: Optional[str] = None,
        branch: str = "data",
        author_name: str = "fnet-bot",
        author_email: str = "fnet-bot@users.noreply.github.com",
    ) -> None:
        super().__init__(out_dir, cfg, prune=prune)
        self.enable_push = enable_push
        self.token = token
        self.remote = remote
        self.branch = branch
        self.author_name = author_name
        self.author_email = author_email

    @property
    def push_enabled(self) -> bool:
        return bool(self.enable_push and self.token and self.remote)

    def publish(self) -> None:
        if not self.push_enabled:
            return None  # guarded: never push implicitly
        self._push()

    # What must NEVER land on the public data branch: `_work/` holds raw downloaded
    # waveforms (NIED-licensed — not redistributable) kept for failure debugging;
    # `_excluded/` and state backups are internal store maintenance artefacts.
    PUBLISH_EXCLUDES = ("_work/", "_excluded/", "state.json.bak*", ".gitignore")

    # Written INTO the data branch: Vercel reads vercel.json from the branch it is
    # deploying, so the main-branch `git.deploymentEnabled.data: false` never applies
    # here — without this file EVERY store publish triggers a doomed "astro build"
    # preview deploy (the data branch has no site) and a failure email.
    VERCEL_NO_DEPLOY = '{\n  "git": { "deploymentEnabled": false },\n  "github": { "enabled": false }\n}\n'

    @classmethod
    def write_publish_gitignore(cls, out_dir) -> str:
        """Write the publish-exclusion `.gitignore` + no-deploy `vercel.json` into
        ``out_dir`` (idempotent).

        Shared by :meth:`_push` and the CI workflow's own publish step so both
        channels produce identical data-branch guard files."""
        with open(os.path.join(str(out_dir), "vercel.json"), "w") as f:
            f.write(cls.VERCEL_NO_DEPLOY)
        p = os.path.join(str(out_dir), ".gitignore")
        with open(p, "w") as f:
            f.write("\n".join(cls.PUBLISH_EXCLUDES) + "\n")
        return p

    def _push(self) -> None:
        """Orphan-branch force-push: re-init the out-dir as a fresh repo and push it as `branch`.

        Token is injected into the push URL only (never committed).  `remote` is the
        `owner/repo` slug or a full https URL."""
        remote = self.remote or ""
        if remote.startswith("http://") or remote.startswith("https://"):
            base = remote
        else:
            base = f"https://github.com/{remote}.git"
        # inject the token as x-access-token (same as the workflow)
        push_url = base.replace("https://", f"https://x-access-token:{self.token}@", 1)
        d = self.out_dir

        def run(*args: str) -> None:
            subprocess.run(args, cwd=d, check=True)

        git_dir = os.path.join(d, ".git")
        if os.path.isdir(git_dir):
            subprocess.run(["rm", "-rf", git_dir], check=True)
        run("git", "init", "-q", "-b", self.branch)
        run("git", "config", "user.name", self.author_name)
        run("git", "config", "user.email", self.author_email)
        self.write_publish_gitignore(d)
        run("git", "add", "-A")
        stamp = to_iso(utcnow())
        # allow the no-change case to be a soft success, like the workflow
        commit = subprocess.run(["git", "commit", "-q", "-m", f"events: {stamp}"], cwd=d)
        if commit.returncode != 0:
            return None
        run("git", "push", "-f", push_url, self.branch)
        return None
