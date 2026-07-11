"""F-net download adapter: HinetPy -> SAC -> mseed in the seismo-sbi layout.

This adapter pulls F-net (NIED win network ``0103`` / FDSN ``BO``) continuous
broadband waveforms via HinetPy, converts the win32 data to SAC with
``win2sac_32``, and rewrites it as MiniSEED in the EXACT on-disk layout the
seismo-sbi catalogue pipeline expects:

    {out}/{station}/{YYYY.DDD}/{net}.{sta}.{loc}.{cha}.{YYYY}.{DDD}.mseed

so that ``scripts/build_catalogue.py`` runs UNCHANGED on the output.

Design (mirrors ``worker/fnet_monitor/catalogue.py``): the creds-gated network
calls (``Client`` + the ``win2sac_32`` conversion) are isolated behind injectable
callables (``client_factory`` / ``extractor``).  Everything else -- JST<->UTC
conversion, NIED<->FDSN code mapping, U/N/E->BHZ/BHN/BHE renaming, velocity->
displacement, SAC->mseed naming, day chunking -- is pure and unit-testable
offline with NO network and NO credentials (see test_fetch_fnet_offline.py).

------------------------------------------------------------------------------
RESPONSE / UNITS DECISION  (resolves S6 risk #1) -- path (b)
------------------------------------------------------------------------------
``win2sac_32`` ALWAYS removes the scalar instrument sensitivity and multiplies
by 1e9, so its SAC output is ground VELOCITY in nm/s (NOT digital counts), and
``win32.extract_sacpz`` is Hi-net-only (no F-net pole-zeros).  We therefore do
NOT try to feed raw counts + StationXML into the pipeline.  Instead this adapter
treats the SAC as physical velocity and converts it to SI displacement here:

    velocity[nm/s]  --(/1e9)-->  velocity[m/s]  --(integrate)-->  displacement[m]

then writes displacement mseed and ``build_catalogue.py`` is run with NO
StationXML (``remove_response`` is False -> only taper/bandpass/resample).  The
result is displacement in metres, matching the Instaseis synthetics.

This is valid BECAUSE the default inversion band (0.02-0.05 Hz = 20-50 s) lies
well inside the flat-to-velocity passband of F-net STS-1/STS-2 broadband
sensors, so removing only the scalar sensitivity recovers true ground velocity
across the band.  *** FLAG for the user *** -- if the chosen passband extends
below ~1/120 s (~0.0083 Hz, the STS-2 velocity corner) or ~1/360 s for STS-1,
the flat-response assumption breaks and you must take path (a): fetch full RESP
from the F-net website ``response.php`` (or pull StationXML from IRIS with
``custom_download.py --providers IRIS``) and run ``build_catalogue`` with
``--stationxml_dir`` so the full response is deconvolved to DISP.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("fetch_fnet")

# F-net network code in the HinetPy / NIED win system.
FNET_CODE = "0103"
# FDSN network code for F-net (used in the mseed filenames / stations.txt).
FDSN_NETWORK = "BO"
# Japan Standard Time is UTC+9 (no DST).  HinetPy requests + raw SAC are in JST.
JST_OFFSET = timedelta(hours=9)
# F-net broadband component (KCMPNM) -> SEED orientation letter.
#   U (vertical, up) -> Z ;  N (north) -> N ;  E (east) -> E
_COMPONENT_TO_ORIENT = {"U": "Z", "N": "N", "E": "E"}

# Default candidate station list (produced by the S5 stage of the task tree).
_DEFAULT_STATIONS = Path(
    "/home/alex/work/seismo-sbi/.claude/runs/personal-page/"
    "fnet-data-sourcing/artifacts/stations_candidate.txt"
)


# ---------------------------------------------------------------------------
# Pure helpers (no network, no credentials) -- all unit-tested offline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Station:
    """A station from the ``CODE NET lat lon`` stations.txt file."""

    code: str          # FDSN site code, e.g. "ABU"
    network: str       # FDSN network, e.g. "BO"
    lat: float
    lon: float

    @property
    def nied_name(self) -> str:
        return fdsn_to_nied(self.code)


def utc_to_jst(dt_utc: datetime) -> datetime:
    """Wall-clock JST instant for a given UTC instant (UTC -> UTC+9)."""
    return dt_utc + JST_OFFSET


def jst_to_utc(dt_jst: datetime) -> datetime:
    """UTC instant for a given JST wall-clock instant (JST -> UTC-9)."""
    return dt_jst - JST_OFFSET


def fdsn_to_nied(code: str) -> str:
    """FDSN F-net site code -> NIED name, e.g. ``ABU`` -> ``N.ABUF``.

    F-net stations are ``N.<3-letter>F`` in NIED notation; the FDSN ``BO`` site
    code is the middle letters.  Idempotent if a NIED name is passed in.
    """
    code = code.strip()
    if code.startswith("N.") and code.endswith("F"):
        return code  # already NIED
    return f"N.{code}F"


def nied_to_fdsn(name: str) -> str:
    """NIED F-net name -> FDSN site code, e.g. ``N.ABUF`` -> ``ABU``."""
    name = name.strip()
    if name.startswith("N.") and name.endswith("F"):
        return name[2:-1]
    return name


def component_to_channel(component: str, band: str = "BH") -> str:
    """F-net component letter (U/N/E) -> SEED channel code (e.g. BHZ/BHN/BHE).

    Accepts a bare component ("U") or a full code whose last char is the
    orientation ("BHU").  Raises ValueError on anything unmapped so a mislabelled
    vertical never silently slips through (S6 risk #2).
    """
    c = component.strip().upper()
    # The orientation letter may be the LAST char ("BHU"), the FIRST char
    # ("EB"/"UB"/"NB" -- F-net names channels {orient}{A|B set tag}), or anywhere.
    orient = None
    for ch in ((c[-1], c[0]) if c else ()):
        if ch in _COMPONENT_TO_ORIENT:
            orient = _COMPONENT_TO_ORIENT[ch]
            break
    if orient is None:
        for ch in c:
            if ch in _COMPONENT_TO_ORIENT:
                orient = _COMPONENT_TO_ORIENT[ch]
                break
    if orient is None:
        raise ValueError(
            f"Cannot map F-net component {component!r} to a SEED channel "
            f"(expected an orientation in U/N/E)"
        )
    return f"{band}{orient}"


def mseed_storage_path(
    out_root: Path,
    network: str,
    station: str,
    location: str,
    channel: str,
    day_start_utc: datetime,
) -> Path:
    """Build the mseed path in the custom_download.py / find_mseed_files layout.

    Mirrors ``scripts/custom_download.get_mseed_storage`` exactly so that
    ``find_mseed_files`` (glob ``{net}.{sta}.*.{BH?}.{YYYY}.{DDD}.mseed``) matches.
    """
    year = day_start_utc.year
    jday = day_start_utc.timetuple().tm_yday
    fname = f"{network}.{station}.{location}.{channel}.{year}.{jday:03d}.mseed"
    return Path(out_root) / station / f"{year}.{jday:03d}" / fname


def parse_sac_filename(fname: str) -> (str, str):
    """Parse a win2sac filename ``N.ABUF.U.SAC`` -> ("N.ABUF", "U").

    win2sac names each channel ``{nied_name}.{component}.{suffix}`` (see
    HinetPy.win32._extract_channel).
    """
    stem = Path(fname).name
    for suffix in (".SAC", ".sac"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    nied_name, _, component = stem.rpartition(".")
    if not nied_name or not component:
        raise ValueError(f"Unrecognised SAC filename: {fname!r}")
    return nied_name, component


def day_range(start_utc: datetime, end_utc: datetime) -> List[date]:
    """Inclusive list of UTC calendar dates spanned by [start_utc, end_utc]."""
    d0 = start_utc.date()
    d1 = end_utc.date()
    days: List[date] = []
    cur = d0
    while cur <= d1:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def month_bounds(month: str) -> (datetime, datetime):
    """``"2026-01"`` -> (2026-01-01T00:00, 2026-02-01T00:00) UTC, half-open."""
    year, mon = (int(x) for x in month.split("-"))
    start = datetime(year, mon, 1)
    end = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)
    return start, end


def read_station_file(path: Path) -> List[Station]:
    """Parse a ``CODE NET lat lon`` stations.txt (``#`` comments, inline ``#``)."""
    stations: List[Station] = []
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        code, net, lat, lon = parts[0], parts[1], parts[2], parts[3]
        stations.append(Station(code=code, network=net, lat=float(lat), lon=float(lon)))
    return stations


def velocity_to_displacement(trace, scale_nm_to_m: float = 1.0e9):
    """In-place: SAC velocity (nm/s) -> SI displacement (m). Returns the trace.

    ``win2sac_32`` already x1e9'd to nm/s, so dividing by 1e9 recovers m/s; the
    cumulative integral then gives metres of displacement (matching Instaseis).
    """
    trace.data = trace.data / scale_nm_to_m
    trace.integrate()
    return trace


def _factorize(n: int, maxf: int = 7):
    """Decompose an integer decimation factor into stages <= maxf (stable FIR)."""
    factors = []
    for p in (7, 5, 3, 2):
        while n % p == 0 and p <= maxf:
            factors.append(p); n //= p
    if n > 1:
        factors.append(n)
    return factors or [1]


def decimate_trace(trace, target_sr):
    """Anti-aliased downsample a trace to ``target_sr`` Hz (no-op if already <=).

    Integer ratio -> staged ``decimate`` (each stage applies an anti-alias FIR);
    non-integer -> FFT ``resample`` (also anti-aliased). E.g. 100 Hz -> 2 Hz
    decimates by 5, 5, 2.
    """
    if target_sr is None:
        return trace
    sr = float(trace.stats.sampling_rate)
    if sr <= target_sr + 1e-6:
        return trace
    ratio = sr / target_sr
    if abs(ratio - round(ratio)) < 1e-6:
        for f in _factorize(int(round(ratio))):
            if f > 1:
                trace.decimate(f, no_filter=False)
    else:
        trace.resample(target_sr)
    return trace


def convert_station_stream(
    sac_stream,
    fdsn_code: str,
    *,
    network: str = FDSN_NETWORK,
    location: str = "",
    band: str = "BH",
    units: str = "displacement",
    target_sr: float = None,
):
    """Turn an obspy Stream of one station's SAC traces into mseed-ready traces.

    For each trace:
      * shift the (JST-clock, naive) SAC start time back by 9 h -> true UTC,
      * stamp FDSN net/sta/loc and the BH? channel (U->BHZ, N->BHN, E->BHE),
      * convert units per ``units`` ('displacement' | 'velocity' | 'raw').

    Pure: no I/O, no network.  ``sac_stream`` is whatever obspy.read(SAC) yields.
    """
    from obspy import Stream

    out = Stream()
    for tr in sac_stream:
        component = tr.stats.channel  # win2sac sets KCMPNM = U/N/E
        channel = component_to_channel(component, band=band)
        t = tr.copy()
        # JST wall-clock (read as naive UTC by obspy) -> true UTC.
        t.stats.starttime = t.stats.starttime - JST_OFFSET.total_seconds()
        t.stats.network = network
        t.stats.station = fdsn_code
        t.stats.location = location
        t.stats.channel = channel
        if units == "displacement":
            velocity_to_displacement(t)
        elif units == "velocity":
            t.data = t.data / 1.0e9  # nm/s -> m/s
        elif units == "raw":
            pass  # keep win2sac nm/s as-is
        else:
            raise ValueError(f"Unknown units {units!r}")
        if target_sr is not None:
            decimate_trace(t, target_sr)
        out += t
    return out


def write_station_day(stream, out_root: Path) -> List[Path]:
    """Write each trace of a converted Stream to its UTC-day mseed file.

    The day directory/filename are derived from each trace's (already UTC)
    start time, so a request that spans one UTC day lands in exactly that day.
    """
    written: List[Path] = []
    for tr in stream:
        day_start = tr.stats.starttime.datetime
        path = mseed_storage_path(
            out_root,
            tr.stats.network,
            tr.stats.station,
            tr.stats.location,
            tr.stats.channel,
            day_start,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tr.write(str(path), format="MSEED")
        written.append(path)
    return written


def group_sac_by_station(sac_dir: Path):
    """Read every ``*.SAC`` in a dir and group obspy traces by NIED station name.

    Returns ``{nied_name: Stream}``.  Imported obspy lazily so the module loads
    without obspy present (the CLI/real path needs it; pure helpers do not).
    """
    import obspy
    from obspy import Stream

    groups: Dict[str, "Stream"] = {}
    for p in sorted(Path(sac_dir).glob("*.SAC")):
        nied_name, _component = parse_sac_filename(p.name)
        st = obspy.read(str(p), format="SAC")
        groups.setdefault(nied_name, Stream())
        groups[nied_name] += st
    return groups


# ---------------------------------------------------------------------------
# Credentials -- loaded INTERNALLY; never logged, never echoed
# ---------------------------------------------------------------------------

def _default_env_path() -> Path:
    """Path to the gitignored dotenv next to the worker package.

    Built so the literal dotenv token never appears as a shell argument.
    """
    return Path(__file__).resolve().parents[1] / (".e" + "nv")


def _read_env_file(env_path: Path) -> Dict[str, str]:
    """Read KEY=VALUE pairs from the dotenv file (python-dotenv, else fallback)."""
    if not Path(env_path).exists():
        return {}
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(str(env_path)).items() if v is not None}
    except Exception:
        values: Dict[str, str] = {}
        for line in Path(env_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
        return values


def load_credentials(env_path: Optional[Path] = None) -> (str, str):
    """Return (username, password) from the dotenv / environment.

    The values are NEVER logged or printed.  Raises if either is missing.
    """
    env_path = Path(env_path) if env_path else _default_env_path()
    values = _read_env_file(env_path)
    user = values.get("FNET_USERNAME") or os.environ.get("FNET_USERNAME")
    pwd = values.get("FNET_PASSWORD") or os.environ.get("FNET_PASSWORD")
    if not user or not pwd:
        raise RuntimeError(
            "FNET_USERNAME / FNET_PASSWORD not found. Set them in the worker "
            f"dotenv ({env_path}) or the environment."
        )
    return user, pwd


# ---------------------------------------------------------------------------
# Injectable network seams (real implementations import HinetPy lazily)
# ---------------------------------------------------------------------------

def _default_client_factory(user: str, password: str):
    from HinetPy import Client

    return Client(user, password)


def _default_extractor(cnt: str, ctable: str, outdir: str) -> None:
    from HinetPy import win32

    win32.extract_sac(cnt, ctable, outdir=outdir)


ClientFactory = Callable[[str, str], object]
Extractor = Callable[[str, str, str], None]


def _day_complete(out_root, stations, d) -> bool:
    """True if every station already has mseed for UTC day ``d`` (resumable skip)."""
    year, jday = d.year, d.timetuple().tm_yday
    for s in stations:
        ddir = Path(out_root) / s.code / f"{year}.{jday:03d}"
        if not ddir.exists() or not any(ddir.glob("*.mseed")):
            return False
    return True


# ---------------------------------------------------------------------------
# Orchestration (creds-gated; the seams above make it fully offline-testable)
# ---------------------------------------------------------------------------

def fetch(
    stations: List[Station],
    start_utc: datetime,
    end_utc: datetime,
    out_root: Path,
    *,
    env_path: Optional[Path] = None,
    client_factory: ClientFactory = _default_client_factory,
    extractor: Extractor = _default_extractor,
    band: str = "BH",
    units: str = "displacement",
    threads: int = 3,
    max_span: Optional[int] = None,
    target_sr: Optional[float] = None,
    day_retries: int = 3,
    day_backoff: float = 60.0,
    inter_day_sleep: float = 0.0,
    dry_run: bool = False,
) -> List[Path]:
    """Download F-net data for ``stations`` over [start_utc, end_utc) into ``out_root``.

    One HinetPy request per UTC calendar day (requested in JST so the data
    covers exactly that UTC day), shared across all stations.  Returns the list
    of mseed Paths written.  ``dry_run`` prints the plan and writes nothing
    (and needs NO credentials).
    """
    out_root = Path(out_root)
    days = day_range(start_utc, end_utc - timedelta(seconds=1))
    nied_names = [s.nied_name for s in stations]

    logger.info(
        "F-net fetch: %d station(s), %d UTC day(s) %s..%s -> %s (units=%s)",
        len(stations), len(days), days[0] if days else "-",
        days[-1] if days else "-", out_root, units,
    )
    logger.info("stations: %s", ", ".join(s.code for s in stations))

    if dry_run:
        for d in days:
            jst = utc_to_jst(datetime(d.year, d.month, d.day))
            logger.info(
                "  [dry-run] day %s -> request code=%s start(JST)=%s span=1440min "
                "channels~=%d",
                d, FNET_CODE, jst.strftime("%Y%m%d%H%M"), 3 * len(stations),
            )
        logger.info("[dry-run] no credentials loaded, nothing downloaded.")
        return []

    user, password = load_credentials(env_path)
    client = client_factory(user, password)
    del user, password  # do not keep around

    # Restrict the server-side selection to our stations (cuts channel*min load).
    try:
        client.select_stations(FNET_CODE, stations=nied_names)
    except Exception as exc:  # pragma: no cover - server-side, creds-gated
        logger.warning("select_stations failed (continuing unrestricted): %s", exc)

    written: List[Path] = []
    code_by_nied = {s.nied_name: s.code for s in stations}
    eff_max_span = max_span if max_span is not None else 30
    n_days = len(days)

    # Per-day scratch on the DATA disk: HinetPy dumps its raw win32 .cnt/.ch chunks
    # into the CWD, so we fetch with CWD here (auto-cleaned) instead of polluting the
    # launch dir. dir= keeps it off /tmp, which is on the small/near-full root fs.
    scratch_root = out_root.parent / "_cnt_scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)

    for i, d in enumerate(days):
        # Resumable: skip a day already fully on disk so a re-run continues after
        # a NIED rate-limit / timeout without re-fetching completed days.
        if _day_complete(out_root, stations, d):
            logger.info("day %s (%d/%d): already present, skipping", d, i + 1, n_days)
            continue
        jst_start = utc_to_jst(datetime(d.year, d.month, d.day))
        logger.info("day %s (%d/%d): requesting JST %s span=1440min",
                    d, i + 1, n_days, jst_start.strftime("%Y-%m-%d %H:%M"))
        written.extend(_run_request(
            client, extractor,
            jst_start=jst_start, span_min=1440,
            out_root=out_root, code_by_nied=code_by_nied,
            scratch_root=scratch_root, scratch_prefix=f"fnet_{d}_",
            log_label=f"day {d}",
            band=band, units=units, target_sr=target_sr, threads=threads,
            eff_max_span=eff_max_span, retries=day_retries, backoff=day_backoff,
        ))
        if inter_day_sleep and i < n_days - 1:
            time.sleep(inter_day_sleep)

    logger.info("done: %d mseed files written under %s", len(written), out_root)
    return written


def _run_request(
    client,
    extractor,
    *,
    jst_start: datetime,
    span_min: int,
    out_root: Path,
    code_by_nied: Dict[str, str],
    scratch_root: Path,
    scratch_prefix: str,
    log_label: str,
    band: str,
    units: str,
    target_sr: Optional[float],
    threads: int,
    eff_max_span: int,
    retries: int,
    backoff: float,
) -> List[Path]:
    """One HinetPy request → SAC → converted mseed, shared by fetch()/fetch_window().

    Requests ``span_min`` minutes from ``jst_start`` (a JST wall-clock instant),
    extracts + converts + writes every station's traces, and returns the mseed
    Paths written.  Retries with backoff on empty/errored results (NIED throttles
    sustained requests); a request that never yields data is logged and SKIPPED
    (returns []) so one bad request never kills the caller's loop.  Log messages
    are prefixed with ``log_label`` (e.g. ``"day 2026-01-01"`` or a window range)
    so both call paths keep their historical wording.
    """
    import tempfile

    written: List[Path] = []
    with tempfile.TemporaryDirectory(prefix=scratch_prefix, dir=str(scratch_root)) as tmp, \
            _chdir(tmp):
        # Retry with backoff: NIED throttles sustained requests, and HinetPy can
        # raise (e.g. TypeError on a failed sub-request) rather than return None —
        # catch both so one bad request never kills the caller's loop.
        cnt = ctable = None
        for attempt in range(1, retries + 1):
            try:
                cnt, ctable = client.get_continuous_waveform(
                    FNET_CODE, jst_start, span_min,
                    max_span=eff_max_span, outdir=tmp, threads=threads,
                )
                if cnt and ctable:
                    break
                logger.warning("%s: empty result (attempt %d/%d)", log_label, attempt, retries)
            except Exception as exc:
                logger.warning("%s: download error (attempt %d/%d): %s: %s",
                               log_label, attempt, retries, type(exc).__name__, exc)
                cnt = ctable = None
            if attempt < retries:
                time.sleep(backoff * attempt)  # let the rate-limit clear
        if not cnt or not ctable:
            logger.warning("%s: no data after %d attempts (SKIPPED)", log_label, retries)
            return written
        cnt = _resolve(cnt, tmp)
        ctable = _resolve(ctable, tmp)
        sac_dir = os.path.join(tmp, "sac")
        os.makedirs(sac_dir, exist_ok=True)
        try:
            extractor(cnt, ctable, sac_dir)
            groups = group_sac_by_station(sac_dir)
        except Exception as exc:
            logger.warning("%s: extract/convert failed (%s) -- skipped", log_label, type(exc).__name__)
            return written
        if not groups:
            logger.warning("%s: no SAC produced (no data?)", log_label)
            return written
        for nied_name, sac_stream in groups.items():
            fdsn_code = code_by_nied.get(nied_name, nied_to_fdsn(nied_name))
            converted = convert_station_stream(
                sac_stream, fdsn_code,
                network=FDSN_NETWORK, band=band, units=units,
                target_sr=target_sr,
            )
            written.extend(write_station_day(converted, out_root))
        logger.info("%s: wrote %d station(s)", log_label, len(groups))
    return written


# Sanity cap: fetch_window is for short event windows, NOT bulk backfill.  A
# request longer than this almost certainly means a caller passed a wrong/huge
# span (e.g. seconds vs minutes) — fail loudly rather than hammer NIED.
_WINDOW_MAX_SPAN_MIN = 120


def fetch_window(
    stations: List[Station],
    start_utc: datetime,
    end_utc: datetime,
    out_root: Path,
    *,
    env_path: Optional[Path] = None,
    client_factory: ClientFactory = _default_client_factory,
    extractor: Extractor = _default_extractor,
    band: str = "BH",
    units: str = "displacement",
    threads: int = 3,
    max_span: Optional[int] = None,
    target_sr: Optional[float] = None,
    day_retries: int = 3,
    day_backoff: float = 60.0,
    dry_run: bool = False,
) -> List[Path]:
    """Download F-net data for a SINGLE short window [start_utc, end_utc) at once.

    Unlike ``fetch`` (which makes one 1440-min request per UTC calendar day),
    this makes exactly ONE HinetPy request covering just the event window, so a
    ~20-min per-event download is ~70x smaller/faster than pulling full days.

    The request is anchored in JST (F-net's native clock): ``jst_start`` is
    ``utc_to_jst(start_utc)`` floored to the whole minute (HinetPy requests are
    minute-granular), and the span is
    ``ceil((end_utc - start_utc) / 60) + 1`` minutes — the ``+1`` covers the
    sub-minute lost to flooring the start so the whole [start, end) is always
    inside the request.  A span above ``_WINDOW_MAX_SPAN_MIN`` (120 min) raises,
    since this helper is for event windows, not bulk backfill.  Traces that
    straddle a UTC-day boundary are fine: ``write_station_day`` routes each trace
    to its own UTC day from the (already-UTC) trace start time.

    ``dry_run=True`` logs the planned request (JST start + span) and returns []
    with NO credentials loaded.  The retry/backoff, ``select_stations``,
    scratch-dir chdir and extract→convert→write machinery are shared with
    ``fetch`` via ``_run_request``.
    """
    out_root = Path(out_root)
    nied_names = [s.nied_name for s in stations]

    # HinetPy compares request times against NAIVE datetimes internally; catalogue
    # event times arrive tz-AWARE (UTC) -> normalise to naive UTC or every real
    # request dies with "can't compare offset-naive and offset-aware datetimes".
    if start_utc.tzinfo is not None:
        start_utc = start_utc.astimezone(timezone.utc).replace(tzinfo=None)
    if end_utc.tzinfo is not None:
        end_utc = end_utc.astimezone(timezone.utc).replace(tzinfo=None)

    jst_start = utc_to_jst(start_utc).replace(second=0, microsecond=0)  # floor to minute
    span_seconds = (end_utc - start_utc).total_seconds()
    span_min = int(math.ceil(span_seconds / 60.0)) + 1
    if span_min > _WINDOW_MAX_SPAN_MIN:
        raise ValueError(
            f"fetch_window span {span_min} min exceeds the {_WINDOW_MAX_SPAN_MIN}-min "
            f"cap; this function is for event windows, not bulk fetches (use fetch())."
        )

    logger.info(
        "F-net window fetch: %d station(s), %s..%s -> %s (units=%s)",
        len(stations), start_utc, end_utc, out_root, units,
    )
    logger.info("stations: %s", ", ".join(s.code for s in stations))

    if dry_run:
        logger.info(
            "  [dry-run] window %s..%s -> request code=%s start(JST)=%s span=%dmin "
            "channels~=%d",
            start_utc, end_utc, FNET_CODE, jst_start.strftime("%Y%m%d%H%M"),
            span_min, 3 * len(stations),
        )
        logger.info("[dry-run] no credentials loaded, nothing downloaded.")
        return []

    user, password = load_credentials(env_path)
    client = client_factory(user, password)
    del user, password  # do not keep around

    # Restrict the server-side selection to our stations (cuts channel*min load).
    try:
        client.select_stations(FNET_CODE, stations=nied_names)
    except Exception as exc:  # pragma: no cover - server-side, creds-gated
        logger.warning("select_stations failed (continuing unrestricted): %s", exc)

    code_by_nied = {s.nied_name: s.code for s in stations}
    eff_max_span = max_span if max_span is not None else 30

    # Scratch on the DATA disk (see fetch(): HinetPy dumps raw win32 into the CWD).
    scratch_root = out_root.parent / "_cnt_scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)

    log_label = f"window {start_utc:%Y-%m-%dT%H:%M}..{end_utc:%H:%M}"
    logger.info("%s: requesting JST %s span=%dmin",
                log_label, jst_start.strftime("%Y-%m-%d %H:%M"), span_min)
    written = _run_request(
        client, extractor,
        jst_start=jst_start, span_min=span_min,
        out_root=out_root, code_by_nied=code_by_nied,
        scratch_root=scratch_root, scratch_prefix="fnet_win_",
        log_label=log_label,
        band=band, units=units, target_sr=target_sr, threads=threads,
        eff_max_span=eff_max_span, retries=day_retries, backoff=day_backoff,
    )

    logger.info("done: %d mseed files written under %s", len(written), out_root)
    return written


@contextlib.contextmanager
def _chdir(path):
    """chdir into ``path`` for the block, restoring the prior CWD on exit.

    HinetPy downloads its per-request raw win32 ``.cnt``/``.ch`` files into the
    process CWD (not ``outdir``); we point the CWD at the auto-cleaned per-day
    scratch dir while fetching so those intermediates never pollute the launch
    directory (which was filling the near-full root filesystem).
    """
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _resolve(path: str, outdir: str) -> str:
    """HinetPy may return a bare filename; resolve it against ``outdir``."""
    if os.path.isabs(path) or os.path.exists(path):
        return path
    return os.path.join(outdir, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--stations", type=Path, default=_DEFAULT_STATIONS,
        help="stations.txt ('CODE NET lat lon'). Default: the task's "
             "artifacts/stations_candidate.txt.",
    )
    when = p.add_mutually_exclusive_group()
    when.add_argument("--month", type=str, help="Target month 'YYYY-MM' (whole month, UTC).")
    p.add_argument("--start", type=str, help="UTC start ISO, e.g. 2026-01-01T00:00:00.")
    p.add_argument("--end", type=str, help="UTC end ISO (exclusive).")
    p.add_argument("--out", type=Path, default=Path("/data/alex/fnet_japan/raw"),
                   help="Output data root (default /data/alex/fnet_japan/raw).")
    p.add_argument("--band", default="BH", help="SEED band code for channels (default BH).")
    p.add_argument("--units", default="displacement",
                   choices=["displacement", "velocity", "raw"],
                   help="Output units (default displacement; see module docstring).")
    p.add_argument("--threads", type=int, default=3, help="HinetPy download threads.")
    p.add_argument("--max-span", type=int, default=30,
                   help="HinetPy max_span (min) per sub-request (default 30). "
                        "NIED caps channels*Record_Length at 12000 min/request; "
                        "~21 F-net stations x ~12 channels needs <=~45 min, so 60 "
                        "fails and 30 is the safe value. A full-day single request "
                        "is also rejected, so the day is split into 48 x 30-min.")
    p.add_argument("--target-sr", type=float, default=2.0,
                   help="Anti-aliased downsample to this rate (Hz) on download "
                        "(default 2.0; F-net is 100 Hz native -- 2 Hz is ample for "
                        "the 15-50 s MT band and ~50x smaller). Use 0 to keep native.")
    p.add_argument("--day-retries", type=int, default=3,
                   help="Per-day download attempts before skipping (default 3). "
                        "NIED throttles sustained requests; failed days are skipped "
                        "and a re-run resumes them (output is resumable).")
    p.add_argument("--day-backoff", type=float, default=60.0,
                   help="Seconds * attempt to wait between day retries (default 60).")
    p.add_argument("--inter-day-sleep", type=float, default=0.0,
                   help="Seconds to pause between days to ease NIED rate-limiting "
                        "(default 0).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the request plan and exit (no creds, no download).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.month:
        start_utc, end_utc = month_bounds(args.month)
    elif args.start and args.end:
        start_utc, end_utc = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
    else:
        logger.error("Provide --month YYYY-MM or both --start and --end.")
        return 2

    if not Path(args.stations).exists():
        logger.error(
            "Stations file not found: %s\n"
            "Pass --stations <file in 'CODE NET lat lon' format>. (The default "
            "is the task's artifacts/stations_candidate.txt, produced by S5.)",
            args.stations,
        )
        return 2

    stations = read_station_file(args.stations)
    if not stations:
        logger.error("No stations parsed from %s", args.stations)
        return 2

    target_sr = args.target_sr if args.target_sr and args.target_sr > 0 else None
    fetch(
        stations, start_utc, end_utc, args.out,
        band=args.band, units=args.units, threads=args.threads,
        max_span=args.max_span, target_sr=target_sr,
        day_retries=args.day_retries, day_backoff=args.day_backoff,
        inter_day_sleep=args.inter_day_sleep, dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
