"""FastAPI web server – REST + WebSocket + camera stream."""

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pybullet as p
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from src.agents.orchestrator import Orchestrator
from src.brain.foundry_client import FoundryClient
from src.config import Config

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Robot Simulator")


# ── Global state (set by start_web_server) ───────────────────────
_orchestrator: Optional[Orchestrator] = None
_foundry_client: Optional[FoundryClient] = None
_physics_client: Optional[int] = None
_config: Optional[Config] = None
_ws_clients: List[WebSocket] = []
_lock = threading.Lock()
_switching_model = False
_ready = False  # True once startup completes

# Pre-import PIL once at module level for faster JPEG encoding
try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None

# Pre-computed camera matrices (constant between calls)
_cam_view = None
_cam_proj = None


def _capture_camera(width: int = 640, height: int = 480) -> bytes:
    """Render a frame from PyBullet's virtual camera and return JPEG bytes."""
    global _cam_view, _cam_proj
    if _physics_client is None:
        return b""

    if _cam_view is None:
        _cam_view = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[0.4, 0.0, 0.3],
            distance=1.2,
            yaw=45,
            pitch=-25,
            roll=0,
            upAxisIndex=2,
        )
        _cam_proj = p.computeProjectionMatrixFOV(
            fov=60, aspect=width / height, nearVal=0.1, farVal=3.0,
        )

    _, _, rgba, _, _ = p.getCameraImage(
        width,
        height,
        viewMatrix=_cam_view,
        projectionMatrix=_cam_proj,
        renderer=p.ER_TINY_RENDERER,
        physicsClientId=_physics_client,
    )
    rgb = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]

    if _PILImage is not None:
        img = _PILImage.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=False)
        return buf.getvalue()
    return _encode_bmp(rgb, width, height)


def _encode_bmp(rgb: np.ndarray, w: int, h: int) -> bytes:
    """Minimal BMP encoder (no PIL dependency)."""
    row_size = (w * 3 + 3) & ~3
    pad = row_size - w * 3
    pixel_size = row_size * h
    file_size = 54 + pixel_size

    header = bytearray(54)
    header[0:2] = b"BM"
    header[2:6] = file_size.to_bytes(4, "little")
    header[10:14] = (54).to_bytes(4, "little")
    header[14:18] = (40).to_bytes(4, "little")
    header[18:22] = w.to_bytes(4, "little")
    header[22:26] = h.to_bytes(4, "little")
    header[26:28] = (1).to_bytes(2, "little")
    header[28:30] = (24).to_bytes(2, "little")
    header[34:38] = pixel_size.to_bytes(4, "little")

    data = bytearray()
    for y in range(h - 1, -1, -1):
        row = rgb[y]
        for px in row:
            data.extend([px[2], px[1], px[0]])  # BGR
        data.extend(b"\x00" * pad)

    return bytes(header) + bytes(data)


async def _broadcast(msg: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    text = json.dumps(msg, default=str)
    dead: List[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ── Routes ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/style.css")
async def style_css():
    css_path = os.path.join(STATIC_DIR, "style.css")
    with open(css_path, encoding="utf-8") as f:
        return Response(f.read(), media_type="text/css")


@app.get("/app.js")
async def app_js():
    js_path = os.path.join(STATIC_DIR, "app.js")
    with open(js_path, encoding="utf-8") as f:
        return Response(f.read(), media_type="application/javascript")


@app.get("/api/scene")
async def api_scene():
    """Return current scene state."""
    if _orchestrator is None:
        return JSONResponse({"error": "not initialised"}, status_code=503)
    # Use the orchestrator's planner scene reference
    from src.simulation.scene import Scene
    # Access scene from the narrator agent
    narrator = _orchestrator._agents[-1]
    scene_desc = narrator._scene.describe()
    ee_pos, ee_rpy = narrator._robot.get_ee_pose()
    return JSONResponse({
        "objects": scene_desc,
        "ee_position": [round(v, 4) for v in ee_pos],
        "ee_orientation_rpy": [round(v, 4) for v in ee_rpy],
    })


@app.get("/api/camera")
async def api_camera():
    """Return a JPEG snapshot from the simulation camera."""
    jpeg = await asyncio.to_thread(_capture_camera)
    if not jpeg:
        return Response(status_code=503)
    # Detect format from header
    media = "image/jpeg" if jpeg[:2] != b"BM" else "image/bmp"
    return Response(jpeg, media_type=media)


@app.post("/api/command")
async def api_command(body: dict):
    """Accept a command and run the agent pipeline in the background.

    Returns 202 immediately so the browser fetch never times out.
    Results are streamed to the client via WebSocket as each agent completes,
    and a final ``command_done`` message carries the full result.
    """
    if _orchestrator is None:
        return JSONResponse({"error": "not initialised"}, status_code=503)

    command = body.get("command", "").strip()
    if not command:
        return JSONResponse({"error": "empty command"}, status_code=400)

    async def _run_pipeline() -> None:
        await _broadcast({"type": "status", "agent": "Orchestrator", "state": "running"})

        async def step_cb(agent_name: str, context: dict) -> None:
            msg: dict = {"type": "agent_step", "agent": agent_name}
            if agent_name == "PlannerAgent":
                msg["plan"] = context.get("plan")
            elif agent_name == "SafetyAgent":
                msg["validation"] = context.get("validation")
            elif agent_name == "ExecutorAgent":
                msg["results"] = context.get("results")
            elif agent_name == "NarratorAgent":
                msg["narration"] = context.get("narration")
            await _broadcast(msg)
            await asyncio.sleep(0)

        _orchestrator.set_step_callback(step_cb)

        try:
            result = await _orchestrator.handle_command(command)
        except Exception as exc:
            print(f"[web] pipeline error: {exc}")
            result = {"error": str(exc)}

        await _broadcast({"type": "status", "agent": "Orchestrator", "state": "done"})
        await _broadcast({
            "type": "command_done",
            "command": command,
            "plan": result.get("plan"),
            "validation": result.get("validation"),
            "results": result.get("results"),
            "narration": result.get("narration"),
        })

    asyncio.create_task(_run_pipeline())
    return JSONResponse({"status": "accepted", "command": command}, status_code=202)


# ── Health / readiness ────────────────────────────────────────────

@app.get("/api/health")
async def api_health():
    """Readiness probe – returns 200 once the server is fully initialised."""
    return JSONResponse({
        "ready": _ready,
        "foundry": _foundry_client is not None,
    }, status_code=200 if _ready else 503)


# ── Model management endpoints ───────────────────────────────────

@app.get("/api/models")
async def api_models():
    """List available models with their status.

    Always returns 200 so the frontend never sees a fetch failure.
    If the client isn't ready yet the models list will be empty.
    """
    if _foundry_client is None:
        return JSONResponse({"models": [], "current": "", "ready": False})
    try:
        models = await asyncio.to_thread(_foundry_client.get_catalog_models)
    except Exception as exc:
        print(f"[web] error fetching models: {exc}")
        models = []
    return JSONResponse({"models": models, "current": _foundry_client.model_alias, "ready": True})


@app.post("/api/model/switch")
async def api_model_switch(body: dict):
    """Switch to a different model. Broadcasts download progress via WebSocket."""
    global _switching_model
    if _foundry_client is None:
        return JSONResponse({"error": "not initialised"}, status_code=503)

    alias = body.get("alias", "").strip()
    if not alias:
        return JSONResponse({"error": "missing alias"}, status_code=400)

    if _switching_model:
        return JSONResponse({"error": "model switch already in progress"}, status_code=409)

    if alias == _foundry_client.model_alias:
        return JSONResponse({"status": "already_active", "alias": alias})

    _switching_model = True

    async def _do_switch():
        global _switching_model
        try:
            loop = asyncio.get_event_loop()

            def progress_cb(model_alias: str, status: str, percent: int | None) -> None:
                asyncio.run_coroutine_threadsafe(
                    _broadcast({
                        "type": "model_progress",
                        "alias": model_alias,
                        "status": status,
                        "percent": percent,
                    }),
                    loop,
                )

            success = await asyncio.to_thread(
                _foundry_client.switch_model, alias, progress_cb
            )
            if success:
                await _broadcast({
                    "type": "model_switched",
                    "alias": _foundry_client.model_alias,
                    "model_id": _foundry_client.model_id,
                })
            else:
                await _broadcast({
                    "type": "model_progress",
                    "alias": alias,
                    "status": "error",
                    "percent": None,
                })
        finally:
            _switching_model = False

    # Run switch in background so the HTTP response returns immediately
    asyncio.create_task(_do_switch())
    return JSONResponse({"status": "switching", "alias": alias})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            # Clients can send commands via WebSocket too
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                msg = {"command": data}

            if "command" in msg and _orchestrator:
                result = await _orchestrator.handle_command(msg["command"])
                await ws.send_text(json.dumps({
                    "type": "command_result",
                    "command": msg["command"],
                    "plan": result.get("plan"),
                    "validation": result.get("validation"),
                    "results": result.get("results"),
                    "narration": result.get("narration"),
                }, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ── Voice transcription endpoint ──────────────────────────────────

@app.post("/api/voice")
async def api_voice(request: Request):
    """Receive WAV audio, transcribe via Whisper, return text.

    Accepts multipart/form-data with an 'audio' file field,
    or raw audio bytes with Content-Type audio/wav or audio/webm.
    """
    if _config is None:
        return JSONResponse({"error": "not initialised"}, status_code=503)

    try:
        content_type = request.headers.get("content-type", "")
        if "multipart" in content_type:
            form = await request.form()
            audio_file = form.get("audio")
            if audio_file is None:
                return JSONResponse({"error": "missing audio field"}, status_code=400)
            audio_bytes = await audio_file.read()
        else:
            audio_bytes = await request.body()

        if not audio_bytes or len(audio_bytes) < 44:
            return JSONResponse({"error": "empty or invalid audio"}, status_code=400)
    except Exception as exc:
        print(f"[web] voice upload error: {exc}")
        return JSONResponse({"error": f"upload error: {exc}"}, status_code=400)

    # Write to temp WAV file
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(audio_bytes)
    tmp.close()

    try:
        from src.input.voice_input import transcribe_with_chunking
        text = await asyncio.to_thread(
            transcribe_with_chunking, tmp.name, _config.whisper_model_alias
        )
    except Exception as exc:
        print(f"[web] transcription error: {exc}")
        text = None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    if text is None:
        return JSONResponse({"error": "transcription failed"}, status_code=500)

    return JSONResponse({"text": text})


# ── Server launcher ──────────────────────────────────────────────

def start_web_server(
    config: Config,
    orchestrator: Orchestrator,
    physics_client: int,
    foundry_client: Optional[FoundryClient] = None,
) -> None:
    """Start the uvicorn server (blocking)."""
    global _orchestrator, _physics_client, _config, _foundry_client, _ready
    _orchestrator = orchestrator
    _physics_client = physics_client
    _config = config
    _foundry_client = foundry_client

    # Pre-warm the model catalog cache so the first /api/models is instant
    if _foundry_client is not None:
        try:
            _foundry_client.get_catalog_models()
            print("[web] model catalog pre-warmed")
        except Exception as exc:
            print(f"[web] catalog pre-warm failed (non-fatal): {exc}")

    # Pre-warm the Whisper pipeline so the first voice request is fast
    try:
        from src.input.voice_input import _get_whisper_pipeline
        _get_whisper_pipeline(config.whisper_model_alias)
    except Exception as exc:
        print(f"[web] Whisper pre-warm failed (non-fatal): {exc}")

    _ready = True

    import uvicorn

    print(f"[web] starting server on http://localhost:{config.web_port}")
    uvicorn.run(app, host="0.0.0.0", port=config.web_port, log_level="info")
