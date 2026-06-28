"""Worker configuration — the F-net / Japan region, thresholds, and the delay window."""

from __future__ import annotations

from dataclasses import dataclass, field

# Generous bounding box around the Japanese islands (F-net coverage), lon/lat.
JAPAN_BBOX = {"minlat": 24.0, "maxlat": 46.0, "minlon": 122.0, "maxlon": 149.0}


@dataclass(frozen=True)
class Config:
    region_name: str = "Japan (F-net)"
    bbox: dict = field(default_factory=lambda: dict(JAPAN_BBOX))

    # Resolvable-event threshold (regional-MT floor ~Mw 3.5).
    min_magnitude: float = 3.5

    # Rolling retention window the frontend slider scrubs.
    window_days: int = 30

    # Archive-lag delay window: only process events older than this (see ARCHITECTURE §6.3).
    delay_minutes: int = 30

    # USGS FDSN-event endpoint (keyless, global detector).
    fdsn_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    # Size of the posterior ensemble written per event (downsampled + rounded).
    n_samples: int = 400

    # Cap on remembered processed ids (keeps state.json bounded).
    max_processed_ids: int = 4000
