import os
import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional

from app.etl.validation import ConstructionInputSchema
from app.etl.transform import ETLTransformer
from app.etl.load import ETLLoader

logger = logging.getLogger("smartflow.etl.collectors.construction")

class ConstructionCollector:
    """
    Polls planned or active road construction zones from government
    infrastructure planning feeds.
    """
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        self.api_url = api_url if api_url is not None else os.getenv("CONSTRUCTION_API_URL", "")
        self.api_key = api_key if api_key is not None else os.getenv("CONSTRUCTION_API_KEY", "")
        self.loader = ETLLoader()
        self.transformer = ETLTransformer()

    async def fetch_raw_data(self) -> List[Dict[str, Any]]:
        """Fetches raw construction zone geometries and schedules."""
        if not self.api_url:
            logger.warning("CONSTRUCTION_API_URL is not configured; skipping construction collection")
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                response = await client.get(self.api_url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                records = payload.get("plans") if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise ValueError("Construction response must contain a plans array")
                return records
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Construction fetch failed: %s", type(e).__name__)
            return []

    async def run(self):
        """Executes the construction collection cycle."""
        logger.info("Starting construction data collection...")
        raw_data = await self.fetch_raw_data()
        
        if not raw_data:
            return

        validated = []
        for item in raw_data:
            try:
                validated.append(ConstructionInputSchema(**item))
            except Exception as e:
                logger.error("Construction validation failed: %s", type(e).__name__)

        if validated:
            transformed = self.transformer.transform_construction(validated)
            try:
                count = await self.loader.load_construction_zones(transformed)
                logger.info(f"Construction Collection Success: {count} zones ingested.")
            except Exception as e:
                logger.error("Failed to load construction zones: %s", type(e).__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = ConstructionCollector()
    asyncio.run(collector.run())
