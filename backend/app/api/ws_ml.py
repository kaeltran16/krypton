"""WebSocket endpoint for real-time ML training progress."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import verify_ws_token
from app.api.ml import _get_train_jobs

logger = logging.getLogger(__name__)
router = APIRouter()

_AUTH_TIMEOUT_S = 10
_COMPLETED_JOB_TTL_S = 60


async def broadcast_ml_event(app, job_id: str, event: dict):
    """Send an event to all connected WS clients for a job."""
    ml_ws = getattr(app.state, "ml_ws_connections", {})
    job_data = ml_ws.get(job_id)
    if not job_data:
        return
    dead = []
    for ws in job_data["clients"]:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        job_data["clients"].remove(ws)


async def close_ml_connections(app, job_id: str):
    """Close all WS connections for a completed/failed job.

    Keeps the ml_ws_connections entry for 60s so late-joining clients
    can still receive a snapshot with the final status, then cleans up.
    """
    ml_ws = getattr(app.state, "ml_ws_connections", {})
    job_data = ml_ws.get(job_id)
    if not job_data:
        return
    for ws in job_data["clients"]:
        try:
            await ws.close()
        except Exception:
            pass
    job_data["clients"] = []

    # Deferred cleanup — keep entry so late-joiners get a snapshot
    loop = asyncio.get_running_loop()
    loop.call_later(_COMPLETED_JOB_TTL_S, lambda: ml_ws.pop(job_id, None))


@router.websocket("/ws/ml-training/{job_id}")
async def ml_training_stream(websocket: WebSocket, job_id: str):
    await websocket.accept()

    # Wait for auth message
    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=_AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect, Exception):
        await websocket.close(code=4001, reason="Auth timeout")
        return

    secret = websocket.app.state.settings.jwt_secret
    if raw.get("type") != "auth" or not verify_ws_token(raw.get("token", ""), secret):
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Verify job exists
    ml_ws = getattr(websocket.app.state, "ml_ws_connections", {})
    job_data = ml_ws.get(job_id)
    train_jobs = _get_train_jobs(websocket.app)
    job = train_jobs.get(job_id)

    if job_data is None or job is None:
        await websocket.close(code=4002, reason="Job not found")
        return

    # Send snapshot with current state
    await websocket.send_json({
        "type": "snapshot",
        "status": job.get("status", "running"),
        "progress": {k: v for k, v in job.get("progress", {}).items()},
        "loss_history": job_data.get("loss_history", {}),
    })

    # Add client to connection pool
    job_data["clients"].append(websocket)
    logger.info("ML WS client connected for job %s (total: %d)", job_id, len(job_data["clients"]))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # Remove from clients if still present
        updated = ml_ws.get(job_id)
        if updated and websocket in updated["clients"]:
            updated["clients"].remove(websocket)
        logger.info("ML WS client disconnected for job %s", job_id)
