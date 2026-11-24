import os
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any

import asyncpg
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("smartflow.backend.main")

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")

class DatabaseManager:
    """
    Manages the lifetime of the PostgreSQL database connection pool.
    Utilizes asyncpg for high-performance concurrent queries.
    """
    def __init__(self, dsn: str | None):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Initializes the database connection pool."""
        if not self.dsn:
            raise RuntimeError("DATABASE_URL is required for database mode")
        try:
            logger.info("Initializing asyncpg database connection pool...")
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=int(os.getenv("DB_MIN_POOL_SIZE", "5")),
                max_size=int(os.getenv("DB_MAX_POOL_SIZE", "20")),
                command_timeout=float(os.getenv("DB_COMMAND_TIMEOUT", "30.0")),
                max_inactive_connection_lifetime=300.0
            )
            logger.info("Database connection pool successfully initialized.")
        except Exception as e:
            logger.critical("Failed to initialize database connection pool: %s", type(e).__name__)
            raise RuntimeError("Database connection pool initialization failed.") from None

    async def disconnect(self) -> None:
        """Gracefully closes all connections in the database connection pool."""
        if self.pool:
            logger.info("Closing database connection pool...")
            await self.pool.close()
            logger.info("Database connection pool closed.")
            self.pool = None

# Single instance of the database manager
db_manager = DatabaseManager(dsn=DATABASE_URL)
requested_mode = os.getenv("SMARTFLOW_MODE", "auto").lower()
if requested_mode not in {"auto", "demo", "live"}:
    raise ValueError("SMARTFLOW_MODE must be auto, demo, or live")
active_mode = "demo" if requested_mode == "demo" else "live"
fallback_reason: str | None = None


def switch_to_demo(reason: str) -> None:
    global active_mode, fallback_reason
    if active_mode != "demo":
        logger.warning("Switching to DEMO mode: %s", reason)
    active_mode = "demo"
    fallback_reason = reason

async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    FastAPI dependency injection provider for acquiring a database connection.
    Ensures the connection is returned to the pool after the request is finished.
    """
    if not db_manager.pool:
        logger.critical("Database connection pool is not initialized.")
        raise RuntimeError("Database connection pool is not initialized.")
    
    async with db_manager.pool.acquire() as connection:
        yield connection


async def get_optional_db() -> AsyncGenerator[asyncpg.Connection | None, None]:
    """Allows map and prediction routes to serve explicitly labeled demo data."""
    if active_mode == "demo":
        yield None
        return
    try:
        if not db_manager.pool:
            raise OSError("Database pool unavailable")
        connection = await db_manager.pool.acquire()
    except (asyncpg.PostgresError, OSError, TimeoutError):
        if requested_mode != "auto":
            raise RuntimeError("Database connection unavailable") from None
        switch_to_demo("Database connection lost")
        yield None
        return
    try:
        yield connection
    finally:
        await db_manager.pool.release(connection)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown lifecycles.
    """
    # Startup actions
    if requested_mode != "demo":
        try:
            await asyncio.wait_for(db_manager.connect(), timeout=4)
        except (RuntimeError, TimeoutError):
            if requested_mode == "live":
                raise
            switch_to_demo("Database unavailable at startup")
    yield
    # Shutdown actions
    await db_manager.disconnect()


# Initialize the FastAPI Application
app = FastAPI(
    title="SmartFlow API",
    description="Real-time traffic intelligence and predictive analytics platform API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

# CORS Middleware Configuration
# Explicitly allowing Next.js dev server, production origins, and local interfaces
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    expose_headers=["Content-Length", "X-Response-Time"]
)

# --- Global Exception Handlers ---

@app.exception_handler(asyncpg.PostgresError)
async def postgres_exception_handler(request: Request, exc: asyncpg.PostgresError):
    """Handles low-level PostgreSQL/PostGIS execution failures."""
    logger.error("Database query error on %s: %s (SQLSTATE %s)", request.url.path,
                 type(exc).__name__, getattr(exc, "sqlstate", None))
    if requested_mode == "auto" and isinstance(exc, asyncpg.exceptions.PostgresConnectionError):
        switch_to_demo("Database connection unavailable")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "A database operation error occurred.",
            "error_type": "DatabaseError",
            "message": "Internal server error"
        }
    )

@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Invalid request parameters."})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handles application-level validation or domain constraint violations."""
    logger.warning("Validation error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Invalid argument or parameter value supplied.",
            "error_type": "ValidationError",
            "message": "Invalid value"
        }
    )

@app.exception_handler(Exception)
async def global_catch_all_handler(request: Request, exc: Exception):
    """Final fallback error handler for unexpected runtime bugs."""
    logger.critical("Unhandled system error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected server error occurred.",
            "error_type": "InternalServerError"
        }
    )


# --- Health & Status Endpoints ---

@app.get("/api/health", response_model=Dict[str, Any], tags=["System"])
async def health_check() -> Dict[str, Any]:
    """
    Performs basic diagnostics on the service and database connection.
    """
    db_ok = False
    db_message = "Not Connected"
    
    if db_manager.pool:
        try:
            # Acquire a connection and run a simple ping query
            async with db_manager.pool.acquire() as conn:
                res = await conn.fetchval("SELECT 1;")
                if res == 1:
                    db_ok = True
                    db_message = "Connected and responding"
        except Exception as e:
            logger.error("Database health check failed: %s", type(e).__name__)
            db_message = "Database health query failed"
            
    status_code = status.HTTP_200_OK if db_ok or active_mode == "demo" else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "online" if db_ok else "demo" if active_mode == "demo" else "degraded",
            "mode": active_mode.upper(),
            "fallback_reason": fallback_reason,
            "environment": os.getenv("APP_ENV", "development"),
            "services": {
                "api": "healthy",
                "database": {
                    "status": "healthy" if db_ok else "unhealthy",
                    "details": db_message
                }
            }
        }
    )

@app.get("/", tags=["System"])
async def root() -> Dict[str, str]:
    """
    Root landing redirect/information point.
    """
    return {
        "message": "Welcome to the SmartFlow API. Head to /api/docs for Swagger documentation.",
        "docs_url": "/api/docs"
    }


# Include Routers (to be created next)
from app.backend.routers import traffic, weather, incidents, analytics, prediction, dashboard

app.include_router(traffic.router, prefix="/api", tags=["Traffic"])
app.include_router(weather.router, prefix="/api", tags=["Weather"])
app.include_router(incidents.router, prefix="/api", tags=["Incidents"])
app.include_router(analytics.router, prefix="/api", tags=["Analytics"])
app.include_router(prediction.router, prefix="/api", tags=["Prediction"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])

# Serve static frontend files
from fastapi.staticfiles import StaticFiles

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

