import os
import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional

from app.etl.validation import TrafficInputSchema
from app.etl.transform import ETLTransformer
from app.etl.load import ETLLoader

logger = logging.getLogger("smartflow.etl.collectors.traffic")

class TrafficCollector:
    """
    Polls real-time traffic telemetry from DOT (Department of Transportation) 
    feeds or sensor networks.
    """
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        self.api_url = api_url if api_url is not None else os.getenv("TRAFFIC_API_URL", "")
        self.api_key = api_key if api_key is not None else os.getenv("TRAFFIC_API_KEY", "")
        self.loader = ETLLoader()
        self.transformer = ETLTransformer()

    async def fetch_raw_data(self) -> List[Dict[str, Any]]:
        """Fetches raw traffic sensor data from the external provider."""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if not self.api_url:
            logger.warning("TRAFFIC_API_URL is not configured; no provider observations were ingested")
            return []
        try:
            # Note: We use a short timeout for real-time telemetry
            async with httpx.AsyncClient(timeout=10.0) as client:
                # In a real scenario, we'd handle pagination or geo-filtering here
                response = await client.get(self.api_url, headers=headers)
                
                response.raise_for_status()
                payload = response.json()
                records = payload.get("data") if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise ValueError("Traffic provider response must contain a data array")
                return records
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Traffic fetch failed: %s", type(exc).__name__)
            return []

    async def run(self):
        """Executes the full collect -> validate -> transform -> load cycle."""
        logger.info("Starting traffic data collection...")
        raw_data = await self.fetch_raw_data()
        
        if not raw_data:
            logger.warning("No traffic data retrieved.")
            return

        validated = []
        for item in raw_data:
            try:
                validated.append(TrafficInputSchema(**item))
            except Exception as e:
                logger.error("Traffic record validation failed: %s", type(e).__name__)

        if validated:
            transformed = self.transformer.transform_traffic(validated)
            try:
                count = await self.loader.load_traffic_readings(transformed)
                logger.info(f"Traffic Collection Success: {count} readings ingested.")
            except Exception as e:
                logger.error("Failed to load traffic readings: %s", type(e).__name__)
        else:
            logger.warning("No valid traffic records to load.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = TrafficCollector()
    asyncio.run(collector.run())
