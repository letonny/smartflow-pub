import unittest
from unittest.mock import patch

from app.database import seed


class SeedSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_target_is_rejected_before_connecting(self):
        with patch.dict("os.environ", {"SMARTFLOW_ALLOW_REMOTE_SEED": ""}), \
             patch.object(seed, "DATABASE_URL", "postgresql://db.example.invalid/smartflow"), \
             patch.object(seed.asyncpg, "connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "requires SMARTFLOW_ALLOW_REMOTE_SEED"):
                await seed.seed_database()
            connect.assert_not_called()

    def test_local_target_allowed_except_in_production(self):
        with patch.dict("os.environ", {"APP_ENV": "development", "SMARTFLOW_ALLOW_REMOTE_SEED": ""}):
            seed.validate_seed_target("postgresql://localhost/smartflow")
        with patch.dict("os.environ", {"APP_ENV": "production", "SMARTFLOW_ALLOW_REMOTE_SEED": ""}):
            with self.assertRaisesRegex(RuntimeError, "requires SMARTFLOW_ALLOW_REMOTE_SEED"):
                seed.validate_seed_target("postgresql://localhost/smartflow")

    def test_missing_target_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required"):
            seed.validate_seed_target(None)
