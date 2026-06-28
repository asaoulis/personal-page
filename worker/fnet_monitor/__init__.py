"""F-net inference worker (skeleton).

Polls a catalogue for new Japan-region earthquakes, runs inference (MOCK in this
skeleton — real NPE is milestone M-D2), and writes the v2 data contract that the
personal-page `/demo` frontend consumes:

  <out>/events.json        GeoJSON index (summaries + per-event ensemble pointer)
  <out>/events/<id>.json   full per-event record incl. the (gamma, delta) posterior
  <out>/state.json         worker-only resume state (NOT served to the frontend)

See worker/README.md and docs/ARCHITECTURE.md (§6) for the design.
"""

__all__ = ["config", "state", "catalogue", "inference", "contract", "run"]
