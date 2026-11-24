import os
import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional

from app.etl.validation import IncidentInputSchema
from app.etl.transform import ETLTransformer
from app.etl.load import ETLLoader

logger = logging.getLogger("smartflow.etl.collectors.incidents")

class IncidentCollector:
    """
    Polls real-time road incidents (accidents, debris, hazards) from 
    emergency response feeds or crowd-sourced data.
    """
    
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        self.api_url = api_url if api_url is not None else os.getenv("INCIDENT_API_URL", "")
        self.api_key = api_key if api_key is not None else os.getenv("INCIDENT_API_KEY", "")
        self.loader = ETLLoader()
        self.transformer = ETLTransformer()

    async def fetch_raw_data(self) -> List[Dict[str, Any]]:
        """Fetches raw incident reports."""
        if not self.api_url:
            logger.warning("INCIDENT_API_URL is not configured; skipping incident collection")
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                response = await client.get(self.api_url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                records = payload.get("incidents") if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    raise ValueError("Incident response must contain an incidents array")
                return records
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Incident fetch failed: %s", type(e).__name__)
            return []

    async def run(self):
        """Executes the incident collection cycle."""
        logger.info("Starting incident data collection...")
        raw_data = await self.fetch_raw_data()
        
        if not raw_data:
            return

        validated = []
        for item in raw_data:
            try:
                validated.append(IncidentInputSchema(**item))
            except Exception as e:
                logger.error("Incident validation failed: %s", type(e).__name__)

        if validated:
            transformed = self.transformer.transform_incident(validated)
            try:
                count = await self.loader.load_incidents(transformed)
                logger.info(f"Incident Collection Success: {count} reports ingested.")
            except Exception as e:
                logger.error("Failed to load incidents: %s", type(e).__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = IncidentCollector()
    asyncio.run(collector.run())
