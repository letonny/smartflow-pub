export interface Reading {
  segment_id: number;
  name: string | null;
  current_speed: number;
  congestion_score: number;
  timestamp: string;
}

export interface DashboardSnapshot {
  mode: "LIVE" | "DEMO";
  source: string;
  fallback_reason: string | null;
  generated_at: string;
  total_records: number;
  throughput_per_minute: number;
  average_speed_kmh: number | null;
  average_congestion: number | null;
  congested_segments: number;
  segment_count: number;
  validation_accepted: number | null;
  validation_rejected: number | null;
  database_status: string;
  etl_status: string;
  latest_ingestion: string | null;
  recent: Reading[];
}

export interface TrafficFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: {
    segment_id: number;
    osm_id: number;
    name: string | null;
    speed_limit: number | null;
    length: number | null;
    current_speed: number | null;
    congestion_score: number | null;
    reading_timestamp: string | null;
  };
}

export interface TrafficCollection {
  type: "FeatureCollection";
  features: TrafficFeature[];
}

export interface SegmentPrediction {
  segment_id: number;
  name: string | null;
  predicted_time_seconds: number;
  free_flow_time_seconds: number;
  current_time_seconds: number | null;
  congestion_score: number;
  rain_intensity: number;
  temperature: number;
  prediction_id: string | null;
  model_source: string;
  inference_ms: number;
}

async function getJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const timeout = AbortSignal.timeout(6000);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const response = await fetch(path, { cache: "no-store", signal: combined });
  if (!response.ok) throw new Error(`API returned ${response.status} for ${path}`);
  return response.json();
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function optionalFinite(value: unknown): value is number | null {
  return value === null || finite(value);
}

export async function getDashboard(signal?: AbortSignal): Promise<DashboardSnapshot> {
  const data = await getJson("/api/dashboard", signal);
  if (!object(data) || (data.mode !== "LIVE" && data.mode !== "DEMO") ||
      typeof data.source !== "string" || typeof data.generated_at !== "string" ||
      !(data.fallback_reason === null || typeof data.fallback_reason === "string") ||
      !finite(data.total_records) || !finite(data.throughput_per_minute) ||
      !optionalFinite(data.average_speed_kmh) || !optionalFinite(data.average_congestion) ||
      !finite(data.congested_segments) || !finite(data.segment_count) ||
      !optionalFinite(data.validation_accepted) || !optionalFinite(data.validation_rejected) ||
      typeof data.database_status !== "string" || typeof data.etl_status !== "string" ||
      !(data.latest_ingestion === null || typeof data.latest_ingestion === "string") ||
      !Array.isArray(data.recent) || !data.recent.every((row: unknown) =>
        object(row) && finite(row.segment_id) && finite(row.current_speed) &&
        finite(row.congestion_score) && typeof row.timestamp === "string" &&
        (row.name === null || typeof row.name === "string"))) {
    throw new Error("Malformed dashboard response");
  }
  return data as unknown as DashboardSnapshot;
}

export async function getTraffic(signal?: AbortSignal): Promise<TrafficCollection> {
  const query = new URLSearchParams({ min_lon: "-122.52", min_lat: "37.68", max_lon: "-122.28", max_lat: "37.86" });
  const data = await getJson(`/api/current-traffic?${query}`, signal);
  if (!object(data) || data.type !== "FeatureCollection" || !Array.isArray(data.features) ||
      !data.features.every((feature: unknown) => object(feature) && object(feature.properties) &&
        finite(feature.properties.segment_id) && object(feature.geometry) &&
        feature.geometry.type === "LineString" && Array.isArray(feature.geometry.coordinates) &&
        feature.geometry.coordinates.every((pair: unknown) => Array.isArray(pair) && pair.length === 2 && pair.every(finite)) &&
        optionalFinite(feature.properties.current_speed) && optionalFinite(feature.properties.congestion_score) &&
        (feature.properties.name === null || typeof feature.properties.name === "string"))) {
    throw new Error("Malformed traffic response");
  }
  return data as unknown as TrafficCollection;
}

export async function getPrediction(segmentId: number, signal?: AbortSignal): Promise<SegmentPrediction> {
  const data = await getJson(`/api/predict/segment/${encodeURIComponent(segmentId)}?record=false`, signal);
  if (!object(data) || !finite(data.segment_id) || !finite(data.predicted_time_seconds) ||
      !finite(data.free_flow_time_seconds) || !optionalFinite(data.current_time_seconds) ||
      !finite(data.inference_ms) || typeof data.model_source !== "string" ||
      !finite(data.congestion_score) || !finite(data.rain_intensity) || !finite(data.temperature) ||
      !(data.name === null || typeof data.name === "string") ||
      !(data.prediction_id === null || typeof data.prediction_id === "string")) {
    throw new Error("Malformed prediction response");
  }
  return data as unknown as SegmentPrediction;
}
