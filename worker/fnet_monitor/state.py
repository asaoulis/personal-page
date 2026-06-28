"""Worker resume state, persisted next to the results as `state.json`.

The cron is stateless across runs and best-effort in timing, so the worker must be
resumable: it remembers the newest processed origin time + recently-processed ids
(for de-duplication) and the measured archive lag. NOT served to the frontend.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from .util import to_iso, utcnow


@dataclass
class State:
    last_time: Optional[str] = None  # ISO of newest processed origin time
    processed_ids: List[str] = field(default_factory=list)
    archive_lag_minutes: Optional[float] = None
    updated: Optional[str] = None

    @classmethod
    def load(cls, path: str) -> "State":
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})
        return cls()

    def remember(self, event_id: str, max_ids: int) -> None:
        if event_id not in self.processed_ids:
            self.processed_ids.append(event_id)
        if len(self.processed_ids) > max_ids:
            self.processed_ids = self.processed_ids[-max_ids:]

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.updated = to_iso(utcnow())
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
