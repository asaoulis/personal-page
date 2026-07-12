import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { type EventFeature, markerSize } from './types';
import { type ColorMode, markerColor } from './coloring';
import FallbackMap from './FallbackMap';

interface Props {
  events: EventFeature[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  colorMode: ColorMode;
}

// Keyless, registration-free vector tiles (OpenFreeMap "positron" = light).
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
const JAPAN_CENTER: [number, number] = [137.5, 37.6];

/** MapLibre GL v5 requires WebGL2 — probe before trying so we can fall back gracefully
 * (headless / GPU-less / WebGL-disabled browsers otherwise render a silent blank map). */
function hasWebGL2(): boolean {
  try {
    return !!document.createElement('canvas').getContext('webgl2');
  } catch {
    return false;
  }
}

export default function MapView({ events, selectedId, onSelect, colorMode }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Map<string, { marker: maplibregl.Marker; el: HTMLButtonElement }>>(
    new Map(),
  );
  const readyRef = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const [supported] = useState(() => hasWebGL2());
  const [glFailed, setGlFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const useFallback = !supported || glFailed;

  // Create the map once (WebGL2 only).
  useEffect(() => {
    if (useFallback || !containerRef.current) return;
    const store = markersRef.current; // stable ref captured for the cleanup closure
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: STYLE_URL,
        center: JAPAN_CENTER,
        zoom: 4.15,
        attributionControl: { compact: true },
      });
    } catch (e) {
      console.warn('MapLibre init failed; using fallback map.', e);
      setGlFailed(true);
      return;
    }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    const rect = containerRef.current.getBoundingClientRect();
    console.info(
      `[demo-map] init: webgl2=${supported} container=${Math.round(rect.width)}x${Math.round(rect.height)} style=${STYLE_URL}`,
    );
    const loadTimer = setTimeout(() => {
      if (!readyRef.current) {
        console.warn('[demo-map] style load timed out (~10s) — using fallback scatter map.');
        setGlFailed(true);
      }
    }, 10000);
    map.on('load', () => {
      readyRef.current = true;
      clearTimeout(loadTimer);
      setLoaded(true);
      map.resize();
      const r = containerRef.current?.getBoundingClientRect();
      console.info(
        `[demo-map] loaded ok: ${Math.round(r?.width ?? 0)}x${Math.round(r?.height ?? 0)}`,
      );
      syncMarkers();
    });
    map.on('error', (e) => {
      const msg = (e && (e.error?.message || String(e.error || ''))) || 'unknown';
      console.warn('[demo-map] maplibre error:', msg);
    });
    mapRef.current = map;

    // Keep the GL canvas sized to its container (a common cause of a "loads but blank" map).
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);
    const kick = setTimeout(() => map.resize(), 400);

    return () => {
      clearTimeout(loadTimer);
      clearTimeout(kick);
      ro.disconnect();
      store.forEach(({ marker }) => marker.remove());
      store.clear();
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useFallback]);

  // Reconcile markers with the visible event set (add new, remove gone) — no full rebuild.
  function syncMarkers() {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const store = markersRef.current;
    const wanted = new Set(events.map((f) => f.properties.id));

    for (const [id, { marker }] of store) {
      if (!wanted.has(id)) {
        marker.remove();
        store.delete(id);
      }
    }
    for (const f of events) {
      const { id, mag, region } = f.properties;
      if (store.has(id)) continue;
      const el = document.createElement('button');
      el.className = 'eq-marker';
      el.style.setProperty('--size', `${markerSize(mag)}px`);
      el.setAttribute('aria-label', `M${mag} · ${region}`);
      el.setAttribute('title', `M${mag} · ${region}`);
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        onSelectRef.current(id);
      });
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat(f.geometry.coordinates)
        .addTo(map);
      store.set(id, { marker, el });
    }
    applyColors();
    applySelection();
  }

  // Marker colour follows the selected colour mode.
  function applyColors() {
    for (const f of events) {
      const m = markersRef.current.get(f.properties.id);
      if (m) m.el.style.setProperty('--mk-color', markerColor(f.properties, colorMode));
    }
  }

  // Toggle the selected class + raise z-index without rebuilding markers.
  function applySelection() {
    for (const [id, { el }] of markersRef.current) {
      const on = id === selectedId;
      el.classList.toggle('is-selected', on);
      el.style.zIndex = on ? '2' : '';
    }
  }

  useEffect(() => {
    if (!useFallback) syncMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, useFallback]);

  useEffect(() => {
    if (!useFallback) applyColors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colorMode]);

  useEffect(() => {
    if (!useFallback) applySelection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  if (useFallback) {
    return (
      <FallbackMap
        events={events}
        selectedId={selectedId}
        onSelect={onSelect}
        colorMode={colorMode}
      />
    );
  }
  return (
    <>
      <div ref={containerRef} className="demo-map" aria-label="Map of recent events" />
      {!loaded && <div className="demo-maploading">Loading basemap…</div>}
    </>
  );
}
