import test from "node:test";
import assert from "node:assert/strict";
import { getDashboard, getPrediction, getTraffic } from "../app/lib/api.ts";

test("dashboard client accepts the API contract and uses no cache", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async (path, options) => {
    assert.equal(path, "/api/dashboard");
    assert.equal(options.cache, "no-store");
    return { ok: true, json: async () => ({ mode: "DEMO", recent: [], total_records: 10,
      source: "synthetic", generated_at: "2026-11-03T00:00:00Z", fallback_reason: null,
      throughput_per_minute: 10, average_speed_kmh: 55, average_congestion: 0.2,
      congested_segments: 0, segment_count: 10, validation_accepted: 10, validation_rejected: 0,
      database_status: "Not used", etl_status: "Active", latest_ingestion: null }) };
  };
  assert.equal((await getDashboard()).total_records, 10);
});

test("client rejects malformed and failed API responses", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ unexpected: true }) });
  await assert.rejects(getDashboard(), /Malformed dashboard response/);
  await assert.rejects(getTraffic(), /Malformed traffic response/);
  await assert.rejects(getPrediction(108), /Malformed prediction response/);
  globalThis.fetch = async () => ({ ok: false, status: 503 });
  await assert.rejects(getDashboard(), /API returned 503/);
});

test("demo map geometry and model result use the expected endpoints", async (context) => {
  const original = globalThis.fetch;
  context.after(() => { globalThis.fetch = original; });
  const paths = [];
  globalThis.fetch = async (path) => {
    paths.push(String(path));
    const body = String(path).startsWith("/api/current-traffic")
      ? { type: "FeatureCollection", features: [{ type: "Feature",
          geometry: { type: "LineString", coordinates: [[-122.385, 37.798], [-122.315, 37.825]] },
          properties: { segment_id: 108, name: "I-80 E", current_speed: 45, congestion_score: 0.55 } }] }
      : { segment_id: 108, name: "I-80 E", predicted_time_seconds: 500,
          free_flow_time_seconds: 234, current_time_seconds: 520, congestion_score: 0.55,
          rain_intensity: 0, temperature: 20, prediction_id: null,
          model_source: "Domain default coefficients", inference_ms: 0.03 };
    return { ok: true, json: async () => body };
  };
  const map = await getTraffic();
  const prediction = await getPrediction(map.features[0].properties.segment_id);
  assert.equal(map.features[0].geometry.coordinates[0][0], -122.385);
  assert.equal(prediction.predicted_time_seconds, 500);
  assert.match(paths[0], /^\/api\/current-traffic\?min_lon=/);
  assert.equal(paths[1], "/api/predict/segment/108?record=false");
});
