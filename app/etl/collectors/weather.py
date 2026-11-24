import os
import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional

from app.etl.validation import WeatherInputSchema
from app.etl.transform import ETLTransformer
from app.etl.load import ETLLoader

logger = logging.getLogger("smartflow.etl.collectors.weather")

class WeatherCollector:
    """
    Polls meteorological snapshots from NOAA or OpenWeather providers.
    """
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        self.api_url = api_url if api_url is not None else os.getenv("WEATHER_API_URL", "")
        self.api_key = api_key if api_key is not None else os.getenv("WEATHER_API_KEY", "")
        self.loader = ETLLoader()
        self.transformer = ETLTransformer()

    async def fetch_raw_data(self) -> List[Dict[str, Any]]:
        """Fetches raw weather data for targeted coordinate areas."""
        if not self.api_url:
            logger.warning("WEATHER_API_URL is not configured; skipping weather collection")
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.api_url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                records = payload.get("snapshots") if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise ValueError("Weather response must contain a snapshots array")
                return records
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Weather fetch failed: %s", type(e).__name__)
            return []

    async def run(self):
        """Executes the weather collection cycle."""
        logger.info("Starting weather data collection...")
        raw_data = await self.fetch_raw_data()
        
        if not raw_data:
            return

        validated = []
        for item in raw_data:
            try:
                validated.append(WeatherInputSchema(**item))
            except Exception as e:
                logger.error("Weather validation failed: %s", type(e).__name__)

        if validated:
            transformed = self.transformer.transform_weather(validated)
            try:
                count = await self.loader.load_weather_snapshots(transformed)
                logger.info(f"Weather Collection Success: {count} snapshots ingested.")
            except Exception as e:
                logger.error("Failed to load weather snapshots: %s", type(e).__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = WeatherCollector()
    asyncio.run(collector.run())
