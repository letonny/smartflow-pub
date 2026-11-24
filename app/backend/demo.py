"""Explicit, in-memory interview data. Never written to PostgreSQL."""
from datetime import datetime, timezone
import math
import time

from app.database.seed import MOCK_SEGMENTS
from app.etl.validation import TrafficInputSchema
from app.etl.transform import ETLTransformer


class DemoStore:
    def __init__(self):
        self.started = time.monotonic()
        self.last_tick = -1
        self.processed = 0
        self.rejected = 0
        self.readings = {}
        self.recent = []
        self.latest = None
        self.batch_times = []

    def refresh(self):
        tick = int((time.monotonic() - self.started) // 10)
        if tick == self.last_tick:
            return
        self.last_tick = tick
        now = datetime.now(timezone.utc)
        validated = []
        for index, segment in enumerate(MOCK_SEGMENTS):
            score = max(0.04, min(0.91, 0.32 + 0.28 * math.sin(tick * 0.55 + index * 0.9)))
            speed = round(segment["speed_limit"] * (1 - score), 1)
            try:
                validated.append(TrafficInputSchema(
                    segment_id=segment["osm_id"], current_speed=speed,
                    congestion_score=round(score, 2), timestamp=now,
                ))
            except ValueError:
                self.rejected += 1
        for reading in ETLTransformer.transform_traffic(validated):
            self.readings[reading["segment_id"]] = reading
            segment = next(s for s in MOCK_SEGMENTS if s["osm_id"] == reading["segment_id"])
            self.recent.insert(0, {
                "segment_id": reading["segment_id"], "name": segment["name"],
                "current_speed": reading["current_speed"],
                "congestion_score": reading["congestion_score"],
                "timestamp": reading["timestamp"].isoformat(),
            })
        self.recent = self.recent[:20]
        self.processed += len(validated)
        self.batch_times.append((time.monotonic(), len(validated)))
        self.batch_times = [(at, count) for at, count in self.batch_times if at >= time.monotonic() - 60]
        self.latest = now.isoformat()

    def features(self, bounds=None):
        self.refresh()
        features = []
        for segment in MOCK_SEGMENTS:
            coords = segment["coordinates"]
            if bounds and not any(bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3] for lon, lat in coords):
                continue
            reading = self.readings[segment["osm_id"]]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in coords]},
                "properties": {
                    "segment_id": segment["osm_id"], "osm_id": segment["osm_id"],
                    "name": segment["name"], "speed_limit": segment["speed_limit"],
                    "length": segment["length"], "current_speed": reading["current_speed"],
                    "congestion_score": reading["congestion_score"],
                    "reading_timestamp": reading["timestamp"].isoformat(),
                    "source_kind": "demo",
                },
            })
        return {"type": "FeatureCollection", "features": features}

    def snapshot(self, reason=None):
        self.refresh()
        readings = list(self.readings.values())
        return {
            "mode": "DEMO", "source": "Synthetic San Francisco corridor observations",
            "fallback_reason": reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": self.processed,
            "throughput_per_minute": sum(count for _, count in self.batch_times),
            "average_speed_kmh": round(sum(r["current_speed"] for r in readings) / len(readings), 1),
            "average_congestion": round(sum(r["congestion_score"] for r in readings) / len(readings), 2),
            "congested_segments": sum(r["congestion_score"] >= 0.6 for r in readings),
            "segment_count": len(readings),
            "validation_accepted": self.processed,
            "validation_rejected": self.rejected,
            "database_status": "Not used in demo",
            "etl_status": "Synthetic generator active",
            "latest_ingestion": self.latest,
            "recent": self.recent[:12],
        }


demo_store = DemoStore()
