# Error Log Monitor Design

## Overview

Lightweight error log monitoring for Krypton's production backend. Structured JSON logging, error persistence to Postgres, a query API endpoint, and a standalone HTML monitor page. Zero new containers or dependencies.

## 1. Structured JSON Logging

JSON logging is unconditional across all environments (dev and production). No `LOG_FORMAT` toggle.

Output format:
```json
{"ts": "2026-03-27T10:08:38.123Z", "level": "ERROR", "module": "app.collector.onchain", "msg": "Tier 1 poll failed: timeout", "pair": "BTC-USDT-SWAP"}
```

### Pair Extraction

The `pair` field is extracted from log messages by pattern matching known pair formats (e.g. `BTC-USDT-SWAP`). This avoids modifying every log call across 32 modules. Extraction happens in the formatter -- if no pair is found, the field is omitted.

### Implementation

New file `app/logging_config.py` containing:
- `JsonFormatter` -- a `logging.Formatter` subclass that outputs JSON lines with `ts`, `level`, `module`, `msg`, and optional `pair` fields
- `setup_logging()` function called from `main.py` that configures the root logger with JSON formatting

## 2. Error Persistence

### ErrorLog Model

New table `error_log`:

| Column | Type | Constraints |
|--------|------|-------------|
| id | BIGINT | PK, auto-increment |
| timestamp | TIMESTAMP(timezone=True) | NOT NULL, indexed |
| level | VARCHAR(10) | NOT NULL (WARNING, ERROR, CRITICAL) |
| module | VARCHAR(100) | NOT NULL |
| message | TEXT | NOT NULL |
| traceback | TEXT | nullable |
| pair | VARCHAR(20) | nullable |

Index on `(timestamp DESC)` for efficient recent-first queries.

### DBErrorHandler

A custom `logging.Handler` subclass in `app/logging_config.py` that:
- Captures log records at WARNING level and above
- Extracts pair from the message using the same logic as the formatter
- Includes traceback text if `exc_info` is present on the record
- Buffers entries in memory and flushes to the `error_log` table periodically (every 5s) or when the buffer reaches 100 entries, using the async session factory
- Handles its own errors gracefully (if the DB write fails, it does not propagate -- logs the failure to stderr)

Attached to the root logger during app startup in `main.py` lifespan.

### Auto-Cleanup

A background task (can run on the existing watchdog loop or a separate periodic task) that:
- Runs every hour
- Deletes rows older than 7 days
- Enforces a hard cap of 10,000 rows (deletes oldest if exceeded)

## 3. API Endpoint

`GET /api/system/errors` in `api/system.py`, alongside the existing health endpoint.

### Authentication

JWT auth, same as all other endpoints.

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| level | string | all | Filter: WARNING, ERROR, CRITICAL |
| module | string | none | Filter by module substring |
| pair | string | none | Filter by pair |
| limit | int | 50 | Rows to return (max 200) |
| offset | int | 0 | Pagination offset |
| since | ISO datetime | none | Only errors after this timestamp |

### Response

```json
{
  "errors": [
    {
      "id": 1234,
      "timestamp": "2026-03-27T10:08:38.123Z",
      "level": "ERROR",
      "module": "app.collector.onchain",
      "message": "Tier 1 poll failed: timeout",
      "traceback": "Traceback (most recent call last):\n  ...",
      "pair": "BTC-USDT-SWAP"
    }
  ],
  "total": 142,
  "has_more": true
}
```

## 4. Standalone Monitor Page

A single `monitor.html` file served by Nginx at `/monitor/`.

### Features

- Login field for JWT token (stored in sessionStorage)
- Polls `/api/system/errors` every 10 seconds
- Polls `/api/system/health` to show system status header (healthy/degraded/unhealthy + key metrics)
- Filter controls: level dropdown, module text input, pair dropdown, time range
- Error table with auto-scroll, new errors highlighted
- Dark theme
- Plain HTML + vanilla JS, no build step, no dependencies

### Nginx Config

Add a location block to the existing `nginx.conf`:
```nginx
location /monitor/ {
    alias /var/www/monitor/;
    try_files $uri /monitor/index.html;
}
```

Volume mount `monitor.html` into the Nginx container.

## 5. Docker Compose Changes (prod only)

In `docker-compose.prod.yml`:

- Add volume mount for `monitor/` directory to the `nginx` service

No new containers. No changes to `docker-compose.yml` (dev).

## 6. File Changes Summary

| File | Change |
|------|--------|
| New: `app/logging_config.py` | JsonFormatter, DBErrorHandler, pair extraction, setup_logging() |
| `app/main.py` | Replace basicConfig with setup_logging(), attach DBErrorHandler in lifespan, add cleanup task |
| `app/db/models.py` | New ErrorLog model |
| New: Alembic migration | error_log table |
| `app/api/system.py` | New GET /api/system/errors endpoint |
| `docker-compose.prod.yml` | monitor volume mount on nginx |
| `nginx/nginx.conf` | /monitor/ location block |
| New: `monitor/index.html` | Standalone monitoring page |
