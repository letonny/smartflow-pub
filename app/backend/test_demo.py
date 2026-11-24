import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from unittest.mock import patch

import asyncpg

from fastapi.testclient import TestClient

from app.backend import main as backend
from app.backend.demo import demo_store
from app.ml.model import TravelTimeModel


class DemoContractTests(unittest.TestCase):
    def setUp(self):
        self.previous_mode = backend.active_mode
        backend.active_mode = "demo"
        backend.app.dependency_overrides.clear()
        self.client = TestClient(backend.app)

    def tearDown(self):
        backend.active_mode = self.previous_mode

    def test_demo_contract_map_and_prediction(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["mode"], "DEMO")

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        snapshot = dashboard.json()
        self.assertEqual(snapshot["mode"], "DEMO")
        self.assertGreater(snapshot["total_records"], 0)
        self.assertEqual(snapshot["database_status"], "Not used in demo")

        map_response = self.client.get("/api/current-traffic", params={
            "min_lon": -122.52, "min_lat": 37.68, "max_lon": -122.28, "max_lat": 37.86,
        })
        self.assertEqual(map_response.status_code, 200)
        features = map_response.json()["features"]
        self.assertEqual(len(features), 10)
        self.assertTrue(all(-122.52 < feature["geometry"]["coordinates"][0][0] < -122.28 for feature in features))
        self.assertTrue(all(feature["properties"]["source_kind"] == "demo" for feature in features))

        segment_id = features[0]["properties"]["segment_id"]
        prediction = self.client.get(f"/api/predict/segment/{segment_id}")
        self.assertEqual(prediction.status_code, 200)
        self.assertIsNone(prediction.json()["prediction_id"])
        self.assertGreater(prediction.json()["predicted_time_seconds"], 0)
        self.assertGreaterEqual(prediction.json()["inference_ms"], 0)
        self.assertEqual(prediction.json()["traffic_source"], "demo")

    def test_invalid_segment_and_viewport(self):
        self.assertEqual(self.client.get("/api/predict/segment/999999").status_code, 404)
        response = self.client.get("/api/current-traffic", params={
            "min_lon": 1, "min_lat": 1, "max_lon": 0, "max_lat": 2,
        })
        self.assertEqual(response.status_code, 400)


class ModelGuardTests(unittest.TestCase):
    def test_nonfinite_and_zero_features_rejected(self):
        model = TravelTimeModel()
        for values in [(1000, 0, 0, 0, 20), (1000, 50, float("nan"), 0, 20), (1000, 50, 0, -1, 20)]:
            with self.assertRaises(ValueError):
                model.predict(*values)

    def test_invalid_training_rows_are_skipped(self):
        model = TravelTimeModel()
        result = model.fit([{"length": 0, "speed_limit": 50, "actual_time": 100,
                             "congestion_score": 0.2, "rain_intensity": 0, "temperature": 20}])
        self.assertEqual(result["status"], "skipped")


class LiveDashboardContractTests(unittest.TestCase):
    def test_database_snapshot_uses_observed_values(self):
        connection = AsyncMock()
        connection.fetchrow.side_effect = [
            {"segment_count": 2, "average_speed_kmh": 35.5, "average_congestion": 0.65, "congested_segments": 1, "non_provider_segments": 0},
            {"total_records": 42, "throughput_per_minute": 3, "latest_ingestion": datetime.now(timezone.utc)},
        ]
        connection.fetch.return_value = [{"segment_id": 1, "name": "Test road", "current_speed": 35.5,
                                         "congestion_score": 0.65, "timestamp": datetime.now(timezone.utc)}]
        async def override():
            yield connection
        backend.app.dependency_overrides[backend.get_optional_db] = override
        try:
            response = TestClient(backend.app).get("/api/dashboard")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["mode"], "LIVE")
            self.assertEqual(data["total_records"], 42)
            self.assertIsNone(data["validation_rejected"])
            self.assertEqual(connection.fetchrow.call_args_list[1].args[1], False)
            self.assertEqual(connection.fetch.call_args.args[1], False)
        finally:
            backend.app.dependency_overrides.clear()

    def test_sql_error_returns_500_without_switching_to_demo(self):
        connection = AsyncMock()
        connection.fetchrow.side_effect = asyncpg.exceptions.UndefinedTableError("sensitive diagnostic")
        async def override():
            yield connection
        previous_mode = backend.active_mode
        backend.active_mode = "live"
        backend.app.dependency_overrides[backend.get_optional_db] = override
        try:
            with patch.object(backend, "requested_mode", "auto"), patch.dict("os.environ", {"API_DEBUG": "true"}):
                response = TestClient(backend.app, raise_server_exceptions=False).get("/api/dashboard")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(backend.active_mode, "live")
            self.assertNotIn("sensitive diagnostic", response.text)
        finally:
            backend.active_mode = previous_mode
            backend.app.dependency_overrides.clear()

    def test_seeded_database_snapshot_stays_demo(self):
        connection = AsyncMock()
        connection.fetchrow.side_effect = [
            {"segment_count": 2, "average_speed_kmh": 35.5, "average_congestion": 0.65,
             "congested_segments": 1, "non_provider_segments": 1},
            {"total_records": 42, "throughput_per_minute": 3,
             "latest_ingestion": datetime.now(timezone.utc)},
        ]
        connection.fetch.return_value = []
        async def override():
            yield connection
        backend.app.dependency_overrides[backend.get_optional_db] = override
        try:
            response = TestClient(backend.app).get("/api/dashboard")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["mode"], "DEMO")
            self.assertEqual(connection.fetchrow.call_args_list[1].args[1], True)
            self.assertEqual(connection.fetch.call_args.args[1], True)
        finally:
            backend.app.dependency_overrides.clear()
