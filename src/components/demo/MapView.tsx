import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { type EventFeature, sourceColor, markerSize } from './types';

interface Props {
  events: EventFeature[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

// Keyless, registration-free vector tiles (OpenFreeMap "positron" = light).
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
const JAPAN_CENTER: [number, number] = [137.5, 37.6];

export default function MapView({ events, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const readyRef = useRef(false);
  // Keep the latest onSelect without re-creating the map.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: JAPAN_CENTER,
      zoom: 4.15,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => {
      readyRef.current = true;
      map.resize(); // ensure correct sizing once the grid row settles
      syncMarkers();
    });
    mapRef.current = map;
    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Rebuild markers whenever the visible events or the selection change.
  function syncMarkers() {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = events.map((f) => {
      const { id, mag, region, source_type } = f.properties;
      const el = document.createElement('button');
      el.className = 'eq-marker' + (id === selectedId ? ' is-selected' : '');
      el.style.setProperty('--size', `${markerSize(mag)}px`);
      el.style.setProperty('--mk-color', sourceColor(source_type));
      el.setAttribute('aria-label', `M${mag} — ${region}`);
      el.setAttribute('title', `M${mag} — ${region}`);
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        onSelectRef.current(id);
      });
      return new maplibregl.Marker({ element: el }).setLngLat(f.geometry.coordinates).addTo(map);
    });
  }

  useEffect(() => {
    syncMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, selectedId]);

  // Ease toward the selected event.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedId) return;
    const f = events.find((e) => e.properties.id === selectedId);
    if (f) map.easeTo({ center: f.geometry.coordinates, duration: 600 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  return <div ref={containerRef} className="demo-map" aria-label="Map of recent events" />;
}
