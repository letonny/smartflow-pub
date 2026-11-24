"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getDashboard, getPrediction, getTraffic,
  type DashboardSnapshot, type SegmentPrediction, type TrafficCollection, type TrafficFeature,
} from "./lib/api";

const BOUNDS = { west: -122.52, east: -122.28, south: 37.68, north: 37.86 };

function point([longitude, latitude]: [number, number]) {
  return `${((longitude - BOUNDS.west) / (BOUNDS.east - BOUNDS.west)) * 1000},${((BOUNDS.north - latitude) / (BOUNDS.north - BOUNDS.south)) * 700}`;
}

function congestionColor(score: number | null) {
  if (score === null) return "#7c8ca2";
  if (score >= 0.65) return "#fb7185";
  if (score >= 0.4) return "#fbbf24";
  return "#3dd7b4";
}

function formattedTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function duration(seconds: number | null | undefined) {
  return seconds == null || !Number.isFinite(seconds) ? "—" : `${(seconds / 60).toFixed(1)} min`;
}

function TrafficMap({ data, selected, onSelect, loading, unavailable }: {
  data: TrafficCollection | null;
  selected: number | null;
  onSelect: (id: number) => void;
  loading: boolean;
  unavailable: boolean;
}) {
  const [zoom, setZoom] = useState(1);
  const features = data?.features ?? [];
  return (
    <div className="map-wrap">
      <div className="map-controls" aria-label="Map zoom controls">
        <button aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(2.5, value + 0.25))}>+</button>
        <button aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(1, value - 0.25))}>−</button>
      </div>
      <svg className="traffic-map" viewBox="0 0 1000 700" role="img" aria-label="Geographic traffic segments in the San Francisco Bay Area">
        <defs>
          <pattern id="map-grid" width="55" height="55" patternUnits="userSpaceOnUse">
            <path d="M 55 0 L 0 0 0 55" fill="none" stroke="#21364a" strokeWidth="1" />
          </pattern>
          <linearGradient id="water" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#10283c"/><stop offset="1" stopColor="#0b1c2e"/></linearGradient>
        </defs>
        <rect width="1000" height="700" fill="#0c1929" />
        <path d="M 775 0 L 1000 0 L 1000 700 L 735 700 C 755 570 705 425 785 295 C 825 225 760 95 775 0" fill="url(#water)" />
        <path d="M 0 0 L 0 700 L 110 700 C 75 540 85 440 28 330 L 0 280 Z" fill="#0d2533" />
        <rect width="1000" height="700" fill="url(#map-grid)" opacity=".65" />
        <g transform={`translate(500 350) scale(${zoom}) translate(-500 -350)`}>
          <g className="map-labels" fill="#49657b" fontSize="18" fontWeight="600" letterSpacing="2">
            <text x="355" y="235">SAN FRANCISCO</text>
            <text x="810" y="145">OAKLAND</text>
            <text x="788" y="440" transform="rotate(90 788 440)">SAN FRANCISCO BAY</text>
            <text x="90" y="620">PACIFIC OCEAN</text>
          </g>
          {features.map((feature: TrafficFeature) => {
            const id = feature.properties.segment_id;
            const path = feature.geometry.coordinates.map((coordinate) => point(coordinate)).join(" ");
            const color = congestionColor(feature.properties.congestion_score);
            return (
              <g key={id}>
                <polyline points={path} fill="none" stroke="#03101c" strokeWidth="17" strokeLinecap="round" strokeLinejoin="round" />
                <polyline points={path} fill="none" stroke={color} strokeWidth={selected === id ? 9 : 6} strokeLinecap="round" strokeLinejoin="round" opacity={selected === null || selected === id ? 1 : 0.65} />
                <polyline points={path} fill="none" stroke="transparent" strokeWidth="27" className="map-segment" role="button" tabIndex={0}
                  aria-label={`Select ${feature.properties.name ?? `segment ${id}`}`}
                  onClick={() => onSelect(id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(id); }}>
                  <title>{feature.properties.name ?? `Segment ${id}`} · {feature.properties.current_speed ?? "No speed"} km/h</title>
                </polyline>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="map-caption">SF BAY AREA · WGS84 / EPSG:4326 <span>{features.length} segments in viewport</span></div>
      {features.length === 0 && <div className="map-empty">{loading ? "Loading spatial data…" : unavailable ? "Map data unavailable" : "No segments in this viewport"}</div>}
    </div>
  );
}

function Metric({ label, value, detail, accent = "cyan" }: { label: string; value: string; detail: string; accent?: "cyan" | "teal" | "amber" }) {
  return <div className={`metric metric-${accent}`}><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-detail">{detail}</div></div>;
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardSnapshot | null>(null);
  const [traffic, setTraffic] = useState<TrafficCollection | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [prediction, setPrediction] = useState<SegmentPrediction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [predictionError, setPredictionError] = useState<string | null>(null);
  const [apiLatency, setApiLatency] = useState<number | null>(null);
  const [inferenceLatency, setInferenceLatency] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [predictionLoading, setPredictionLoading] = useState(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const start = performance.now();
    try {
      const [dashboardResult, trafficResult] = await Promise.allSettled([getDashboard(signal), getTraffic(signal)]);
      if (signal?.aborted) return;
      if (dashboardResult.status === "fulfilled") setDashboard(dashboardResult.value);
      if (trafficResult.status === "fulfilled") {
        const nextTraffic = trafficResult.value;
        setTraffic(nextTraffic);
        setSelected((previous) => previous && nextTraffic.features.some((feature) => feature.properties.segment_id === previous)
          ? previous : nextTraffic.features[0]?.properties.segment_id ?? null);
      }
      const failures = [dashboardResult, trafficResult].filter((result) => result.status === "rejected");
      setError(failures.length ? failures.map((result) => result.reason instanceof Error ? result.reason.message : "API request failed").join("; ") : null);
      setApiLatency(failures.length ? null : Math.round(performance.now() - start));
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "Unable to reach the SmartFlow API");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => void refresh(controller.signal), 5000);
    return () => { controller.abort(); window.clearInterval(interval); };
  }, [refresh]);

  useEffect(() => {
    if (selected === null) {
      setPrediction(null);
      setInferenceLatency(null);
      return;
    }
    const controller = new AbortController();
    setPredictionError(null);
    setPredictionLoading(true);
    setPrediction(null);
    setInferenceLatency(null);
    void getPrediction(selected, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setPrediction(result); setInferenceLatency(result.inference_ms); }
    }).catch((cause) => {
      if (!controller.signal.aborted) { setPrediction(null); setInferenceLatency(null); setPredictionError(cause instanceof Error ? cause.message : "Prediction unavailable"); }
    }).finally(() => { if (!controller.signal.aborted) setPredictionLoading(false); });
    return () => controller.abort();
  }, [selected, dashboard?.generated_at]);

  const chosen = traffic?.features.find((feature) => feature.properties.segment_id === selected);
  const selectedScore = chosen?.properties.congestion_score ?? null;
  const delta = prediction?.current_time_seconds != null ? prediction.predicted_time_seconds - prediction.current_time_seconds : null;
  const offlineDemo = dashboard?.mode === "DEMO" && dashboard.database_status === "Not used in demo";

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-icon">S<span>F</span></div><div><strong>SmartFlow</strong><small>SPATIAL TRAFFIC INTELLIGENCE</small></div></div>
      <div className="topbar-right"><span className="update-note">AUTO REFRESH · 5 SEC</span><span className={`mode-pill ${dashboard?.mode === "LIVE" ? "live" : "demo"}`}><span className="status-dot" />{dashboard?.mode ?? "CONNECTING"}</span></div>
    </header>

    <div className="content">
      <div className="intro"><div><div className="eyebrow">OPERATIONS / OVERVIEW</div><h1>Traffic intelligence <span>at a glance.</span></h1><p>Corridor observations, spatial context, and explainable travel time estimates.</p></div><div className="asof">LAST UPDATED<strong>{formattedTime(dashboard?.generated_at)}</strong></div></div>
      {error && <div className="alert" role="alert"><strong>Data refresh issue</strong><span>{error}{dashboard || traffic ? ". Last successful data remains visible." : ". Check that the API is running."}</span><button onClick={() => void refresh()}>Retry</button></div>}
      {dashboard?.mode === "DEMO" && <div className="demo-notice"><span>DEMO DATA</span> Synthetic, seeded, or unverified observations are displayed. No external live traffic feed is implied.{dashboard.fallback_reason && <small>Fallback: {dashboard.fallback_reason}</small>}</div>}
      {loading && <div className="loading" role="status">Connecting to SmartFlow API…</div>}

      <section className="metrics-grid" aria-label="Traffic overview">
        <Metric label="RECORDS PROCESSED" value={dashboard?.total_records.toLocaleString() ?? "—"} detail={offlineDemo ? "Synthetic session total" : dashboard ? "Database total" : "Awaiting data"} />
        <Metric label="INGESTION THROUGHPUT" value={dashboard ? `${dashboard.throughput_per_minute}/min` : "—"} detail={offlineDemo ? "Synthetic rows in past minute" : dashboard ? "Database writes in past minute" : "Awaiting data"} accent="teal" />
        <Metric label="AVERAGE SPEED" value={dashboard?.average_speed_kmh == null ? "—" : `${dashboard.average_speed_kmh} km/h`} detail="Latest reading per segment" />
        <Metric label="CONGESTED SEGMENTS" value={dashboard ? `${dashboard.congested_segments} / ${dashboard.segment_count}` : "—"} detail="Congestion score ≥ 0.60" accent="amber" />
        <Metric label="API LATENCY" value={apiLatency === null ? "—" : `${apiLatency} ms`} detail="Dashboard + map round trip" />
        <Metric label="MODEL INFERENCE" value={inferenceLatency === null ? "—" : `${inferenceLatency.toFixed(2)} ms`} detail="Server model execution" accent="teal" />
      </section>

      <div className="main-grid">
        <section className="panel map-panel"><div className="panel-heading"><div><div className="eyebrow">GEOSPATIAL NETWORK</div><h2>Corridor map</h2></div><div className="legend"><span><i className="legend-good"/>Clear</span><span><i className="legend-mid"/>Moderate</span><span><i className="legend-bad"/>Heavy</span></div></div><TrafficMap data={traffic} selected={selected} onSelect={setSelected} loading={loading} unavailable={Boolean(error)} /><div className="map-footer">Select a corridor to inspect its latest speed and request a prediction.<span>WGS84 VIEWPORT · SF BAY AREA</span></div></section>

        <section className="panel prediction-panel"><div className="panel-heading"><div><div className="eyebrow">PREDICTIVE ENGINE</div><h2>Travel time forecast</h2></div><div className="panel-symbol">↗</div></div><label className="select-label" htmlFor="segment-select">ROAD SEGMENT</label><select id="segment-select" value={selected ?? ""} onChange={(event) => setSelected(Number(event.target.value))} disabled={!traffic?.features.length}><option value="" disabled>Select a segment</option>{traffic?.features.map((feature) => <option key={feature.properties.segment_id} value={feature.properties.segment_id}>{feature.properties.name ?? `Segment ${feature.properties.segment_id}`}</option>)}</select>
          <div className="corridor-summary"><div><span>Current speed</span><strong>{chosen?.properties.current_speed == null ? "—" : `${chosen.properties.current_speed} km/h`}</strong></div><div><span>Congestion</span><strong style={{ color: congestionColor(selectedScore) }}>{selectedScore === null ? "—" : `${Math.round(selectedScore * 100)}%`}</strong></div></div>
          <div className="prediction-result"><span>MODEL PREDICTION</span><strong>{prediction && prediction.segment_id === selected ? duration(prediction.predicted_time_seconds) : "—"}</strong><small role="status">{predictionLoading ? "Calculating…" : prediction?.model_source ?? "Select a segment"}</small></div>
          <div className="comparison"><div><span>Current estimate</span><strong>{prediction && prediction.segment_id === selected ? duration(prediction.current_time_seconds) : "—"}</strong></div><div><span>Difference</span><strong>{delta === null || prediction?.segment_id !== selected ? "—" : `${delta >= 0 ? "+" : ""}${(delta / 60).toFixed(1)} min`}</strong></div></div>
          {predictionError && <p className="inline-error">{predictionError}</p>}
          <p className="model-note">Current estimate uses observed speed. Prediction uses the local gradient descent model with congestion and weather features. The offline generator uses 20°C and no rain.</p>
        </section>
      </div>

      <div className="bottom-grid"><section className="panel feed-panel"><div className="panel-heading"><div><div className="eyebrow">OBSERVATION STREAM</div><h2>Recent traffic feed</h2></div><span className="feed-status"><span className="status-dot"/>{error ? "RECONNECTING" : !dashboard ? "CONNECTING" : offlineDemo ? "SYNTHETIC" : dashboard.mode === "DEMO" ? "SEEDED / UNVERIFIED" : "POLLING"}</span></div><div className="feed-table"><div className="feed-row feed-head"><span>TIME</span><span>CORRIDOR</span><span>SPEED</span><span>CONGESTION</span></div>{dashboard?.recent.length ? dashboard.recent.map((reading, index) => {
        const inViewport = traffic?.features.some((feature) => feature.properties.segment_id === reading.segment_id) ?? false;
        return <button className="feed-row" key={`${reading.segment_id}-${reading.timestamp}-${index}`} onClick={() => setSelected(reading.segment_id)} disabled={!inViewport} title={inViewport ? "Inspect this segment" : "Outside the current map viewport"}><span>{formattedTime(reading.timestamp)}</span><span>{reading.name ?? `Segment ${reading.segment_id}`}</span><span>{reading.current_speed.toFixed(1)} km/h</span><span style={{ color: congestionColor(reading.congestion_score) }}>{Math.round(reading.congestion_score * 100)}%</span></button>;
      }) : <div className="empty-row">No observations yet.</div>}</div></section>
      <section className="panel pipeline-panel"><div className="panel-heading"><div><div className="eyebrow">PIPELINE HEALTH</div><h2>System monitor</h2></div><span className={`mode-tag ${dashboard?.mode === "LIVE" ? "live" : "demo"}`}>{dashboard?.mode ?? "OFFLINE"}</span></div><div className="pipeline-line"><span>ETL status</span><strong>{dashboard?.etl_status ?? "Unavailable"}</strong></div><div className="pipeline-line"><span>Database</span><strong>{dashboard?.database_status ?? "Disconnected"}</strong></div><div className="pipeline-line"><span>Accepted / validated</span><strong>{dashboard?.validation_accepted?.toLocaleString() ?? "Unavailable"}</strong></div><div className="pipeline-line"><span>Rejected</span><strong>{dashboard?.validation_rejected?.toLocaleString() ?? "Unavailable"}</strong></div><div className="pipeline-line"><span>Latest successful ingestion</span><strong>{formattedTime(dashboard?.latest_ingestion)}</strong></div><div className="pipeline-source"><span>DATA SOURCE</span><strong>{dashboard?.source ?? "Waiting for API"}</strong></div><p className="pipeline-hint">Live validation counters require a shared ETL telemetry store. This panel shows unavailable instead of estimating them.</p></section></div>
      <footer>SMARTFLOW <span>ASYNC ETL · POSTGIS · FASTAPI · CUSTOM REGRESSION</span></footer>
    </div>
  </main>;
}
