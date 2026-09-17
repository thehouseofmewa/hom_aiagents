"""HTTP API for starting the HOM voice-agent pipeline."""

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, status
from fastapi.staticfiles import StaticFiles
from loguru import logger

from hom_backend.pipeline_building.agent_pipeline import (
    AgentConfig,
    run_pipeline,
)

app = FastAPI(title="HOM Voice Bot Backend")
_pipeline_task: asyncio.Task[None] | None = None
_pipeline_lock = asyncio.Lock()
WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def _pipeline_finished(task: asyncio.Task[None]) -> None:
    global _pipeline_task

    _pipeline_task = None
    if not task.cancelled() and task.exception() is not None:
        logger.opt(exception=task.exception()).error("Pipeline failed")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a healthy response for service probes."""
    return {"status": "ok"}


@app.post("/pipeline", status_code=status.HTTP_202_ACCEPTED)
async def start_pipeline(request: Request) -> dict[str, Any]:
    """Return the WebSocket endpoint used to start a pipeline session."""
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return {"status": "ready", "wsUrl": f"{scheme}://{request.url.netloc}/ws"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Run one Pipecat pipeline for the connected WebSocket client."""
    global _pipeline_task

    async with _pipeline_lock:
        if _pipeline_task is not None and not _pipeline_task.done():
            await websocket.close(code=1008, reason="A pipeline is already running")
            return

        config = AgentConfig()
        config.validate()
        await websocket.accept()
        _pipeline_task = asyncio.create_task(run_pipeline(config, websocket))
        _pipeline_task.add_done_callback(_pipeline_finished)

    await _pipeline_task


app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")