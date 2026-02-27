# Backend Plan A: Foundation (Phases 1-2, Tasks 1-6)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Scaffold the Krypton backend project with FastAPI, configuration system, Docker setup, database models, Alembic migrations, and wire everything into the application lifecycle.

**Architecture:** Single async FastAPI process. This plan establishes the project structure, configuration, and database layer that all subsequent plans depend on.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (async + asyncpg), Alembic, Pydantic, pydantic-settings, Docker, pytest + pytest-asyncio

**Depends on:** Nothing (first plan)
**Unlocks:** Plans B, C, D

---

## Phase 1: Project Scaffold & Configuration

### Task 1: Initialize project structure and dependencies

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/requirements.txt`
- Create: `.gitignore`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

**Step 1: Create directory structure**

Only create directories needed for this plan. Subsequent plans create their own packages.

```bash
mkdir -p backend/app/db/migrations backend/tests
```

Create `__init__.py` in each package:
```bash
touch backend/app/__init__.py backend/app/db/__init__.py backend/tests/__init__.py
```

**Step 2: Create .gitignore**

```gitignore
# .gitignore
__pycache__/
*.pyc
*.pyo
.env
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/
*.db
.idea/
.vscode/
*.swp
*.swo
```

**Step 3: Create pyproject.toml**

```toml
# backend/pyproject.toml
[project]
name = "krypton"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
```

**Step 4: Create requirements.txt**

Only include dependencies needed for this plan. Plans B-D add their own.

```
# backend/requirements.txt
fastapi==0.133.1
uvicorn[standard]==0.41.0
sqlalchemy[asyncio]==2.0.47
asyncpg==0.31.0
alembic==1.18.4
httpx==0.28.1
pydantic==2.12.5
pydantic-settings==2.13.1
pyyaml==6.0.3
python-dotenv==1.2.1

# testing
pytest==9.0.2
pytest-asyncio==0.25.3
pytest-cov==7.0.0
```

**Step 5: Create minimal FastAPI app**

```python
# backend/app/main.py
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

**Step 6: Create test conftest**

```python
# backend/tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
```

**Step 7: Write test for health endpoint**

```python
# backend/tests/test_health.py
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 8: Run test**

```bash
cd backend && python -m pytest tests/test_health.py -v
```

Expected: PASS

**Step 9: Commit**

```bash
git add .gitignore backend/
git commit -m "chore: scaffold backend project with FastAPI and test setup"
```

---

### Task 2: Configuration system (Pydantic Settings + YAML)

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/config.yaml`
- Create: `backend/.env.example`
- Test: `backend/tests/test_config.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_config.py
from pathlib import Path

from app.config import Settings, load_yaml_config


def test_default_settings(tmp_path, monkeypatch):
    """Settings should load with defaults when no yaml provided."""
    monkeypatch.setenv("KRYPTON_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/krypton")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings()
    assert settings.krypton_api_key == "test-key"
    assert settings.openrouter_api_key == "test-or-key"
    assert len(settings.pairs) > 0
    assert len(settings.timeframes) > 0


def test_load_yaml_config(tmp_path):
    """YAML config should override defaults."""
    yaml_content = """
pairs:
  - BTC-USDT-SWAP
timeframes:
  - 15m
collector:
  mode: scheduled
  polling_interval_seconds: 600
  rest_poll_interval_seconds: 120
engine:
  signal_threshold: 60
  llm_threshold: 40
  llm_timeout_seconds: 20
  traditional_weight: 0.70
  llm_weight: 0.30
api:
  ws_heartbeat_seconds: 15
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    config = load_yaml_config(yaml_file)
    assert config["pairs"] == ["BTC-USDT-SWAP"]
    assert config["collector"]["mode"] == "scheduled"
    assert config["engine"]["traditional_weight"] == 0.70


def test_load_yaml_config_empty_file(tmp_path):
    """Empty YAML file should return empty dict, not None."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("")

    config = load_yaml_config(yaml_file)
    assert config == {}


def test_settings_with_yaml_override(tmp_path, monkeypatch):
    """Settings should merge YAML values over defaults."""
    yaml_content = """
pairs:
  - ETH-USDT-SWAP
collector:
  mode: scheduled
  polling_interval_seconds: 600
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    monkeypatch.setenv("KRYPTON_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/krypton")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KRYPTON_CONFIG_PATH", str(yaml_file))

    settings = Settings()
    assert settings.pairs == ["ETH-USDT-SWAP"]
    assert settings.collector_mode == "scheduled"
    assert settings.collector_polling_interval_seconds == 600
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_config.py -v
```

Expected: FAIL — `ImportError: cannot import name 'Settings'`

**Step 3: Implement config.py**

```python
# backend/app/config.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings


_YAML_SECTION_PREFIX = {
    "collector": "collector_",
    "engine": "engine_",
    "api": "api_",
}


def load_yaml_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _flatten_yaml(config: dict) -> dict:
    """Flatten nested YAML sections into prefixed flat keys matching Settings fields."""
    flat = {}
    for key, value in config.items():
        prefix = _YAML_SECTION_PREFIX.get(key)
        if prefix and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{prefix}{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


class Settings(BaseSettings):
    # secrets (from .env)
    krypton_api_key: str
    openrouter_api_key: str
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    database_url: str = "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton"
    redis_url: str = "redis://localhost:6379/0"

    # pairs and timeframes
    pairs: list[str] = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    timeframes: list[str] = ["15m", "1h", "4h"]

    # collector
    collector_mode: Literal["event_driven", "scheduled"] = "event_driven"
    collector_polling_interval_seconds: int = 900
    collector_rest_poll_interval_seconds: int = 300

    # engine
    engine_signal_threshold: int = 50
    engine_llm_threshold: int = 30
    engine_llm_timeout_seconds: int = 30
    engine_traditional_weight: float = 0.60
    engine_llm_weight: float = 0.40

    # api
    api_ws_heartbeat_seconds: int = 30

    # config file path
    krypton_config_path: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context) -> None:
        if self.krypton_config_path:
            path = Path(self.krypton_config_path)
            if path.exists():
                yaml_config = load_yaml_config(path)
                flat = _flatten_yaml(yaml_config)
                for key, value in flat.items():
                    if hasattr(self, key):
                        object.__setattr__(self, key, value)
```

**Step 4: Create config.yaml and .env.example**

```yaml
# backend/config.yaml
pairs:
  - BTC-USDT-SWAP
  - ETH-USDT-SWAP

timeframes:
  - 15m
  - 1h
  - 4h

collector:
  mode: event_driven
  polling_interval_seconds: 900
  rest_poll_interval_seconds: 300

engine:
  signal_threshold: 50
  llm_threshold: 30
  llm_timeout_seconds: 30
  traditional_weight: 0.60
  llm_weight: 0.40

api:
  ws_heartbeat_seconds: 30
```

```bash
# backend/.env.example
KRYPTON_API_KEY=your-api-key-here
OPENROUTER_API_KEY=your-openrouter-key-here
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
DATABASE_URL=postgresql+asyncpg://krypton:krypton@postgres:5432/krypton
REDIS_URL=redis://redis:6379/0
KRYPTON_CONFIG_PATH=config.yaml
```

**Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_config.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/config.py backend/config.yaml backend/.env.example backend/tests/test_config.py
git commit -m "feat: add configuration system with pydantic settings and YAML override"
```

---

### Task 3: Docker and Docker Compose setup

**Files:**
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `backend/.dockerignore`

**Step 1: Create Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Create .dockerignore**

```
# backend/.dockerignore
__pycache__
*.pyc
.env
.git
tests/
.pytest_cache/
```

**Step 3: Create docker-compose.yml**

Note: `env_file` uses `required: false` so `docker compose up` works before `.env` is created (copy from `.env.example`).

```yaml
# docker-compose.yml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - path: ./backend/.env
        required: false
    volumes:
      - ./backend/config.yaml:/app/config.yaml:ro
      - ./backend/app/prompts:/app/app/prompts:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: krypton
      POSTGRES_PASSWORD: krypton
      POSTGRES_DB: krypton
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U krypton"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

**Step 4: Copy .env.example to .env for local dev**

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` with real values (or keep placeholders for Docker-only testing).

**Step 5: Verify build**

```bash
docker compose build api
```

Expected: Build succeeds

**Step 6: Verify stack starts**

```bash
docker compose up -d
curl http://localhost:8000/health
docker compose down
```

Expected: `{"status":"ok"}`

**Step 7: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore docker-compose.yml
git commit -m "chore: add Docker and docker-compose setup"
```

---

## Phase 2: Database Layer

### Task 4: SQLAlchemy models (candles + signals)

**Files:**
- Create: `backend/app/db/models.py`
- Create: `backend/app/db/database.py`
- Test: `backend/tests/test_db_models.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_db_models.py
from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import Candle, Signal


def test_candle_model():
    candle = Candle(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        timestamp=datetime(2026, 2, 27, 14, 0, tzinfo=timezone.utc),
        open=Decimal("67000.5"),
        high=Decimal("67200.0"),
        low=Decimal("66900.0"),
        close=Decimal("67100.0"),
        volume=Decimal("1234.56"),
    )
    assert candle.pair == "BTC-USDT-SWAP"
    assert candle.timeframe == "15m"
    assert candle.close == Decimal("67100.0")


def test_signal_model():
    signal = Signal(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        direction="LONG",
        final_score=78,
        traditional_score=72,
        llm_opinion="confirm",
        llm_confidence="HIGH",
        explanation="Strong bullish setup.",
        entry=Decimal("67420"),
        stop_loss=Decimal("66890"),
        take_profit_1=Decimal("67950"),
        take_profit_2=Decimal("68480"),
        raw_indicators={"rsi": 32, "ema_9": 67100},
    )
    assert signal.direction == "LONG"
    assert signal.final_score == 78
    assert signal.raw_indicators["rsi"] == 32
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_db_models.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement database.py**

```python
# backend/app/db/database.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, database_url: str):
        self.engine: AsyncEngine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def get_session(self) -> AsyncSession:
        async with self.session_factory() as session:
            yield session

    async def close(self):
        await self.engine.dispose()
```

**Step 4: Implement models.py**

Use `Mapped[Decimal]` for `Numeric` columns to match actual DB return types.

```python
# backend/app/db/models.py
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", "timestamp", name="uq_candle"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    traditional_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_opinion: Mapped[str | None] = mapped_column(String(16))
    llm_confidence: Mapped[str | None] = mapped_column(String(8))
    explanation: Mapped[str | None] = mapped_column(Text)
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit_1: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit_2: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    raw_indicators: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_signal_pair_tf_created", "pair", "timeframe", "created_at"),
    )
```

**Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_db_models.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add backend/app/db/
git commit -m "feat: add SQLAlchemy models for candles and signals"
```

---

### Task 5: Alembic migrations setup

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/app/db/migrations/env.py`
- Create: `backend/app/db/migrations/script.py.mako` (auto-generated by alembic init)
- Create: `backend/app/db/migrations/versions/` (auto-generated)

**Step 1: Initialize Alembic**

```bash
cd backend && alembic init app/db/migrations
```

**Step 2: Configure alembic.ini**

Edit `backend/alembic.ini`:
- Set `script_location = app/db/migrations`
- Leave `sqlalchemy.url` empty (will be set from env in env.py)

**Step 3: Configure migrations/env.py**

Replace the auto-generated `env.py` with one that:
- Imports `Base` from `app.db.database` and all models from `app.db.models`
- Sets `target_metadata = Base.metadata`
- Reads `DATABASE_URL` from environment for `sqlalchemy.url`
- For offline mode: uses sync URL (replace `asyncpg` with `psycopg2`)
- For online mode: uses sync engine via `create_engine`

Key lines:
```python
import os
from app.db.database import Base
from app.db import models  # noqa: F401 — import so models register with Base

config.set_main_option("sqlalchemy.url", os.environ.get(
    "DATABASE_URL", "postgresql://krypton:krypton@localhost:5432/krypton"
).replace("+asyncpg", ""))

target_metadata = Base.metadata
```

**Step 4: Generate initial migration**

```bash
cd backend && alembic revision --autogenerate -m "create candles and signals tables"
```

Expected: Migration file created in `app/db/migrations/versions/`

**Step 5: Apply migration (requires running postgres)**

```bash
docker compose up -d postgres
cd backend && DATABASE_URL=postgresql://krypton:krypton@localhost:5432/krypton alembic upgrade head
```

Expected: Tables created

**Step 6: Commit**

```bash
git add backend/alembic.ini backend/app/db/migrations/
git commit -m "feat: add Alembic migrations for candles and signals tables"
```

---

### Task 6: Wire config and database into FastAPI lifecycle

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_health.py` (verify existing test still passes)

**Step 1: Update main.py with lifespan**

Wire `Settings` and `Database` into the app so downstream plans (B, C, D) can depend on them.

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.database_url)
    app.state.settings = settings
    app.state.db = db
    yield
    await db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

**Step 2: Update test conftest to handle lifespan**

The existing `create_app()` now uses a lifespan that reads env vars. Tests need env vars set, or we override the lifespan for unit tests.

```python
# backend/tests/conftest.py
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    yield


@pytest.fixture
def app():
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=_test_lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
```

**Step 3: Run all tests**

```bash
cd backend && python -m pytest -v
```

Expected: ALL PASS (health, config, and model tests)

**Step 4: Commit**

```bash
git add backend/app/main.py backend/tests/conftest.py
git commit -m "feat: wire config and database into FastAPI lifecycle"
```
