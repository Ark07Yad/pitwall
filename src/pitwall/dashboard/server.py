"""HTTP and WebSocket server for the dashboard.

Deliberately small. The dashboard is evidence that the engine works, not the
product, and a week spent on it is a week not spent on the models it displays.

State is pushed rather than polled: the browser opens one websocket and receives
a full snapshot at a fixed cadence. Snapshots rather than deltas because the
whole payload is a few kilobytes, and a client that connects mid-race then needs
no catch-up logic - it is correct from the first message.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
#
# fastapi is an optional dependency, so it is imported inside `build_app` rather
# than at module scope. With postponed annotations every hint becomes a string
# that FastAPI resolves against the *module* namespace - where `WebSocket` does
# not exist. It then falls back to treating `socket: WebSocket` as a query
# parameter and rejects every upgrade with `403 {"loc": ["query", "socket"],
# "msg": "Field required"}`, which looks nothing like an import problem.
# Evaluating annotations eagerly resolves them in the enclosing function, where
# the import is in scope.

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from pitwall.dashboard.engine import Engine

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
DEFAULT_PUSH_INTERVAL = 1.0

MISSING_DEPS = "the dashboard needs fastapi and uvicorn:\n    uv sync --extra dashboard"


def build_app(engine: Engine, *, push_interval: float = DEFAULT_PUSH_INTERVAL):
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise SystemExit(MISSING_DEPS) from exc

    app = FastAPI(title="Pitwall")
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return index

    @app.get("/api/state")
    async def state() -> dict:
        return engine.snapshot()

    @app.websocket("/ws")
    async def stream(socket: WebSocket) -> None:
        await socket.accept()

        async def receive() -> None:
            """Let the browser change which car is being advised."""
            try:
                while True:
                    message = json.loads(await socket.receive_text())
                    if driver := message.get("driver"):
                        engine.requested_driver = str(driver).upper()
                        # Force a recompute rather than waiting for the next lap,
                        # or switching driver would appear to do nothing.
                        engine._last_advised_lap = -1
            except Exception:
                return

        reader = asyncio.create_task(receive())
        try:
            while True:
                await socket.send_text(json.dumps(engine.snapshot()))
                await asyncio.sleep(push_interval)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

    @app.on_event("startup")
    async def start_engine() -> None:
        app.state.engine_task = asyncio.create_task(engine.run())

    @app.on_event("shutdown")
    async def stop_engine() -> None:
        task = getattr(app.state, "engine_task", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await engine.feed.aclose()

    return app


def serve(engine: Engine, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise SystemExit(MISSING_DEPS) from exc

    uvicorn.run(build_app(engine), host=host, port=port, log_level="warning")
