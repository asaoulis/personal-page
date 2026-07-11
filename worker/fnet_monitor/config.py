"""Worker configuration — the F-net / Japan region, thresholds, and the delay window."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

# Generous bounding box around the Japanese islands (F-net coverage), lon/lat.
JAPAN_BBOX = {"minlat": 24.0, "maxlat": 46.0, "minlon": 122.0, "maxlon": 149.0}

# ----------------------------------------------------------------- training domain
# The NPE's TRAINING PRIOR (task `source-catalogue-dataset`) covers only the main arc:
#   30.5 <= lat <= 46, 128 <= lon <= 146,
#   EXCLUDING the Izu–Bonin strip (lat < 33 AND lon > 138),
#   depth <= 80 km.
# Events outside this domain produced the garbage island-arc / deep-slab posteriors the
# backfill diagnostics flagged, so the live monitor treats them as terminal `out_of_domain`.
TRAINING_DOMAIN = {"minlat": 30.5, "maxlat": 46.0, "minlon": 128.0, "maxlon": 146.0}
IZU_BONIN_EXCLUSION = {"maxlat": 33.0, "minlon": 138.0}  # drop if lat < 33 AND lon > 138
TRAINING_MAX_DEPTH_KM = 80.0


def in_training_domain(
    lat: Optional[float], lon: Optional[float], depth_km: Optional[float],
    max_depth_km: float = TRAINING_MAX_DEPTH_KM,
) -> Tuple[bool, str]:
    """Is (lat, lon, depth) inside the NPE's training-prior domain?

    Returns ``(ok, reason)`` — `reason` is "" when in-domain, otherwise a human-readable
    explanation for the terminal `out_of_domain` verdict. Any None coordinate is treated as
    unknown and passes its own check (the remaining checks still apply)."""
    d = TRAINING_DOMAIN
    if lat is None or lon is None:
        if depth_km is not None and depth_km > max_depth_km:
            return False, (
                f"depth {depth_km:.0f}km > max_depth_km {max_depth_km:.0f} "
                f"(outside model training domain)")
        return True, ""
    if not (d["minlat"] <= lat <= d["maxlat"] and d["minlon"] <= lon <= d["maxlon"]):
        return False, (
            f"epicentre ({lat:.2f}, {lon:.2f}) outside the training box "
            f"[{d['minlat']},{d['maxlat']}] x [{d['minlon']},{d['maxlon']}] "
            f"(outside model training domain)")
    if lat < IZU_BONIN_EXCLUSION["maxlat"] and lon > IZU_BONIN_EXCLUSION["minlon"]:
        return False, (
            f"epicentre ({lat:.2f}, {lon:.2f}) in the Izu–Bonin exclusion strip "
            f"(lat < {IZU_BONIN_EXCLUSION['maxlat']} and lon > {IZU_BONIN_EXCLUSION['minlon']}) "
            f"(outside model training domain)")
    if depth_km is not None and depth_km > max_depth_km:
        return False, (
            f"depth {depth_km:.0f}km > max_depth_km {max_depth_km:.0f} "
            f"(outside model training domain)")
    return True, ""


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

    # Out-of-domain depth cut: the fiducial Instaseis DB and — more fundamentally — the NPE's
    # training domain only cover shallow events, so a candidate deeper than this is terminal
    # `out_of_domain` (never downloaded / retried).  Env override: FNET_MAX_DEPTH_KM (read at the
    # consumption site in `monitor.tick`, following the codebase's env-at-use style).  The full
    # lat/lon/depth check is `in_training_domain` above.
    max_depth_km: float = TRAINING_MAX_DEPTH_KM

    # USGS FDSN-event endpoint (keyless, global detector).
    fdsn_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    # USGS near-live discovery: origins arrive within minutes–1 h (vs days–weeks for the NIED
    # F-net MT publication), so provisional events are inferred from the USGS origin and the
    # F-net reference attached on publication (supersede-on-match).  USGS magnitudes near the
    # floor are mb-dominated (systematically below Mw ~3.5 detections), so the discovery
    # threshold sits higher than the F-net `min_magnitude`.
    usgs_enabled: bool = True
    usgs_min_magnitude: float = 4.0

    # Size of the posterior ensemble written per event (downsampled + rounded).
    n_samples: int = 400

    # Cap on remembered processed ids (keeps state.json bounded).
    max_processed_ids: int = 4000
