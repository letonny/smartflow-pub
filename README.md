# SmartFlow

SmartFlow is a spatial traffic intelligence project with an asynchronous Python ETL path, PostGIS queries, a FastAPI service, a custom gradient descent travel time model, and a React dashboard. Use it locally to explore how road observations become spatial queries and travel-time estimates. Demo observations are synthetic and are labeled as such throughout the UI.

## What it shows

- Pydantic v2 validation, de-duplication, and transactional asyncpg loading of traffic observations.
- PostGIS GiST indexed road geometry and viewport queries, with the latest reading per segment.
- A custom pure Python linear regression model trained by gradient descent and used by the prediction API.
- A responsive dashboard with an interactive coordinate-based Bay Area map, recent feed, prediction comparison, and pipeline monitor.
- Clear provenance: provider readings, seeded database rows, and offline demo observations are differentiated. A failed database write is never counted as a success.

## Architecture and data flow

```mermaid
flowchart LR
    A[Configured traffic JSON provider] --> B[async httpx collector]
    B --> C[Pydantic validation]
    C --> D[ETL transform and de-duplication]
    D --> E[(PostgreSQL + PostGIS)]
    E --> F[FastAPI spatial and dashboard endpoints]
    E --> G[Travel time model]
    G --> F
    F --> H[React + TypeScript dashboard]
    I[Explicit in-memory demo generator] --> C
    I --> F
```

The external traffic adapter expects JSON shaped as `{"data":[{"segment_id":1,"current_speed":42.5,"congestion_score":0.25}]}` or a bare array of those records. `segment_id` must refer to a row in `road_segments`. The configured scheduler polls the provider, validates records, transforms and deduplicates them, then inserts them in a transaction. In demo mode, the local generator passes through the same traffic validator and transformer and serves the API without a database or external feed. It does **not** pretend to persist records.

## Stack

Python 3.13, FastAPI, asyncio, httpx, Pydantic v2, asyncpg, PostgreSQL/PostGIS, custom pure Python gradient descent, Next.js 16, React 19, TypeScript, CSS. The current model does not depend on scikit-learn at runtime.

## Run the offline demo

Install Python 3.13 and Node.js 20.9 or newer, then from the repository root:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
```

Start the API in terminal one:

```bash
SMARTFLOW_MODE=demo .venv/bin/python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

Start the dashboard in terminal two:

```bash
npm run dev -- --hostname 127.0.0.1
```

Open [http://localhost:3000](http://localhost:3000). The dashboard polls the API every five seconds. No paid service, database, network traffic source, or map tile service is needed. The map shows geographically coherent San Francisco corridors and supports segment selection and zoom. The browser UI itself does not invent metrics when the API is unavailable.

## Run with local PostGIS

Docker Compose publishes PostGIS on the loopback interface. Use a dedicated local database. The seed command applies the schema, updates matching road metadata, and appends synthetic observations on each run.

1. Create a private settings file with `(umask 077 && cp -n .env.example .env)`. If the file already exists, edit it in place.
2. Set `POSTGRES_PASSWORD` privately. For a new volume, choose a unique generated password. For an existing volume, supply its existing database password. Compose applies initialization settings only when creating the database.
3. Set `DATABASE_URL` to the loopback PostgreSQL URI for the role and database named in `compose.yaml`. Its format is `postgresql://ROLE:PASSWORD@127.0.0.1:5432/DATABASE`. Percent-encode special characters in the URI credentials. Keep the raw Compose password and the URI shell-quoted in the local file.

From the repository root in a POSIX-compatible shell, load your trusted local settings and start the services.

```bash
set -a
. ./.env
set +a
docker compose up -d --wait
.venv/bin/python -m app.database.seed
SMARTFLOW_MODE=live .venv/bin/python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

Start the dashboard as in the offline demo. Next.js forwards same-origin `/api/*` requests to the loopback FastAPI service. Database access and provider configuration belong in the Python environment. Any `NEXT_PUBLIC_*` setting is public browser configuration.

| Setting | Local use |
| --- | --- |
| `SMARTFLOW_MODE` | `demo` runs offline, `live` requires the database, and `auto` can fall back to labeled DEMO data. |
| `DB_MIN_POOL_SIZE`, `DB_MAX_POOL_SIZE`, `DB_COMMAND_TIMEOUT` | Tune the database pool and command timeout. |
| `ALLOWED_ORIGINS` | Comma-separated list of allowed browser origins. |
| `TRAFFIC_API_URL`, `TRAFFIC_API_KEY` | Optional traffic endpoint and server-side key. Leave empty in DEMO mode. |
| `WEATHER_API_*`, `INCIDENT_API_*`, `CONSTRUCTION_API_*` | Optional endpoint and key for each additional adapter. |

To run configured collectors, load the same local environment in a separate terminal and run `.venv/bin/python -m app.etl.scheduler`. Use HTTPS endpoints for authenticated feeds.

The other weather, incident, and construction adapters are present but require compatible provider payloads and configuration. The traffic collector does not use sample records as a fallback; a provider failure is logged and produces no write.

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | API and database state, current mode, fallback reason |
| `GET /api/dashboard` | Observed or explicitly synthetic totals, throughput, averages, pipeline state, recent readings |
| `GET /api/current-traffic?min_lon=...&min_lat=...&max_lon=...&max_lat=...` | GeoJSON LineString features for a viewport |
| `GET /api/predict/segment/{id}` | Current speed estimate and model prediction; server inference time. Read only by default; `record=true` writes an audit row. |
| `POST /api/predict` | Prediction for validated explicit features |
| `GET /api/analytics/trends` | Historical hourly PostGIS backed trends |
| `GET /api/weather`, `GET /api/incidents` | Nearby weather and spatial incidents |

Interactive API docs are at [http://localhost:8000/api/docs](http://localhost:8000/api/docs). Live dashboard validation counts are unavailable because the standalone scheduler does not share an in-memory counter with the API. Live throughput means rows written in the past minute; it is not a claim about provider throughput.

## Prediction model

`TravelTimeModel` predicts a multiplier over free flow time:

```text
free_flow_seconds = length_meters / (speed_limit_kmh / 3.6)
multiplier = max(1, w0 + w1*congestion + w2*rain_mm_per_hour + w3*abs(temperature_c - 20))
predicted_seconds = free_flow_seconds * multiplier
```

Training fits the multiplier with mean squared error and explicit gradient descent. The model rejects invalid or nonfinite inference features, skips invalid training rows, and checks for divergent weights. It loads `app/ml/model_weights.json` when present; otherwise it uses documented domain coefficients and the UI says so. The repository contains no evaluated model artifact or held out journey dataset. The synthetic training unit test verifies mechanics, **not predictive accuracy**. A meaningful evaluation would compare MAE/RMSE against observed completed trips on a time separated holdout, including a free flow baseline and per corridor error analysis.

## Previous verification

The previously verified revision passed 38 backend tests and 3 frontend API tests, TypeScript validation, and a Next.js production build. Local PostgreSQL/PostGIS integration and database-backed ML predictions were also verified. These results predate the publication-preparation changes.

## Limitations

- Real external traffic ingestion and provider schema compatibility remain unverified. Offline and seeded observations are synthetic.
- ESLint remains unverified.
- The API is unauthenticated and intended for local development. Bind both servers to loopback, including the dashboard that proxies API requests. Some endpoints can write prediction records.
- Model accuracy on observed trips and production throughput have yet to be evaluated. Dashboard timings describe individual requests.
- The map covers a Bay Area viewport. Live dashboard aggregates scan the readings table, and validation counters are available only for the in-process demo.
