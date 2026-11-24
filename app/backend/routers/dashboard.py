"""Small, truthful dashboard contract for live and offline operation."""
from datetime import datetime, timezone
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.backend import main as backend
from app.backend.demo import demo_store

router = APIRouter()


class RecentReading(BaseModel):
    segment_id: int
    name: str | None
    current_speed: float
    congestion_score: float
    timestamp: datetime


class DashboardSnapshot(BaseModel):
    mode: Literal["LIVE", "DEMO"]
    source: str
    fallback_reason: str | None
    generated_at: datetime
    total_records: int
    throughput_per_minute: int
    average_speed_kmh: float | None
    average_congestion: float | None
    congested_segments: int
    segment_count: int
    validation_accepted: int | None
    validation_rejected: int | None
    database_status: str
    etl_status: str
    latest_ingestion: datetime | None
    recent: list[RecentReading]


@router.get("/dashboard", response_model=DashboardSnapshot)
async def dashboard_snapshot(conn: asyncpg.Connection | None = Depends(backend.get_optional_db)):
    if conn is None:
        return demo_store.snapshot(backend.fallback_reason)

    current = await conn.fetchrow("""
        SELECT count(*)::int AS segment_count,
               avg(r.current_speed)::float AS average_speed_kmh,
               avg(r.congestion_score)::float AS average_congestion,
               count(*) FILTER (WHERE r.congestion_score >= 0.6)::int AS congested_segments,
               count(*) FILTER (WHERE r.source_kind <> 'provider')::int AS non_provider_segments
        FROM road_segments s
        JOIN LATERAL (
          SELECT current_speed, congestion_score, source_kind FROM traffic_readings
          WHERE segment_id = s.id ORDER BY timestamp DESC LIMIT 1
        ) r ON true
    """)
    is_demo_data = current["segment_count"] == 0 or current["non_provider_segments"] > 0
    # Once every current segment is provider backed, keep historical seed rows out
    # of LIVE counters, ingestion time, and the recent feed.
    totals = await conn.fetchrow("""
        SELECT count(*)::int AS total_records,
               count(*) FILTER (WHERE timestamp >= now() - interval '1 minute')::int AS throughput_per_minute,
               max(timestamp) AS latest_ingestion
        FROM traffic_readings
        WHERE $1::boolean OR source_kind = 'provider'
    """, is_demo_data)
    rows = await conn.fetch("""
        SELECT r.segment_id, s.name, r.current_speed,
               r.congestion_score::float AS congestion_score, r.timestamp
        FROM traffic_readings r JOIN road_segments s ON s.id = r.segment_id
        WHERE $1::boolean OR r.source_kind = 'provider'
        ORDER BY r.timestamp DESC LIMIT 12
    """, is_demo_data)
    return DashboardSnapshot(
        mode="DEMO" if is_demo_data else "LIVE",
        source="PostgreSQL (seed or unverified observations included)" if is_demo_data else "PostgreSQL provider observations",
        fallback_reason=None, generated_at=datetime.now(timezone.utc),
        total_records=totals["total_records"],
        throughput_per_minute=totals["throughput_per_minute"],
        average_speed_kmh=round(current["average_speed_kmh"], 1) if current["average_speed_kmh"] is not None else None,
        average_congestion=round(current["average_congestion"], 2) if current["average_congestion"] is not None else None,
        congested_segments=current["congested_segments"], segment_count=current["segment_count"],
        validation_accepted=None, validation_rejected=None,
        database_status="Connected", etl_status="Latest database write observed" if totals["latest_ingestion"] else "Awaiting first write",
        latest_ingestion=totals["latest_ingestion"],
        recent=[RecentReading(**dict(row)) for row in rows],
    )
