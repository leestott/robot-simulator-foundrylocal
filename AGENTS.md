# AGENTS.md – Copilot / AI Agent Instructions

This file provides context for AI coding agents (GitHub Copilot, etc.) working
in the **Robot Arm Simulator with Foundry Local** repository.

## Project Overview

A PyBullet robot-arm simulation controlled by natural-language commands.
The LLM "brain" runs entirely on-device via **Foundry Local** – no cloud APIs,
no API keys. Voice input is supported via a local Whisper model.

A **web UI** serves a live camera view of the simulation alongside a chat
interface so users can type commands and watch the robot execute them in
real time.

The system uses the **Microsoft Agent Framework** to orchestrate multiple
specialised agents (planner, safety validator, executor, scene narrator)
that collaborate to translate natural language into safe, validated robot
actions.

## Repository Layout

```
src/
  app.py               # Entry point – wires all components together
  web_ui.py             # FastAPI web server – REST + WebSocket + camera stream
  config.py             # Centralised Config dataclass + CLI arg parsing
  brain/
    foundry_client.py   # OpenAI-compatible client for Foundry Local
    planner.py          # LLM prompt + JSON-plan parsing & retry logic
    action_schema.py    # Strict schema of allowed tools (move_ee, pick, etc.)
  agents/
    orchestrator.py     # Microsoft Agent Framework multi-agent orchestrator
    planner_agent.py    # Agent: converts NL commands → JSON action plans
    safety_agent.py     # Agent: validates plans against workspace bounds & schema
    executor_agent.py   # Agent: dispatches validated actions to PyBullet
    narrator_agent.py   # Agent: describes scene state in natural language
  executor/
    action_executor.py  # Maps validated action dicts to PyBullet calls
  simulation/
    scene.py            # Scene setup (ground plane, table, target objects)
    robot.py            # Panda robot URDF loader + IK helpers
    grasp.py            # High-level grasp/place sequences
  input/
    text_input.py       # CLI text prompt
    voice_input.py      # Microphone capture + Whisper transcription
  static/
    index.html          # Web UI – single-page app
    style.css           # Web UI styles
    app.js              # Web UI logic (chat, camera, agent status)
tests/
  test_action_schema.py
  test_config.py
  test_executor.py
  test_planner.py
  test_scene_helpers.py
```

## Key Conventions

- **Python 3.10+** – use `from __future__ import annotations` for forward refs.
- **Dataclass config** – all runtime settings live in `Config` (`src/config.py`).
- **Strict action schema** – the LLM may only produce actions listed in
  `TOOL_SCHEMAS` (`src/brain/action_schema.py`). Never add tools there without
  a matching handler in `ActionExecutor._dispatch`.
- **No cloud dependencies** – the project uses Foundry Local exclusively.
  Do not introduce calls to OpenAI, Azure OpenAI, or other cloud LLM services.
- **OpenAI SDK compatibility** – Foundry Local exposes an OpenAI-compatible
  endpoint. Use the `openai` Python package to communicate with it.
- **Virtual environment** – dependencies are in `requirements.txt`; the
  `.venv` is created via `setup.ps1` / `setup.sh` / `setup.bat`.

## Microsoft Agent Framework Integration

The simulation is orchestrated by a multi-agent system built on the
**Microsoft Agent Framework** (via `azure-ai-projects` / Foundry Local).

### Agent Roles

| Agent | Responsibility | Module |
|---|---|---|
| **PlannerAgent** | Translates natural-language commands into JSON action plans using the Foundry Local LLM | `src/agents/planner_agent.py` |
| **SafetyAgent** | Validates plans against workspace bounds, schema constraints, and collision checks | `src/agents/safety_agent.py` |
| **ExecutorAgent** | Dispatches validated actions to PandaRobot / GraspController via PyBullet | `src/agents/executor_agent.py` |
| **NarratorAgent** | Generates a summary of what happened; uses fast template by default, LLM opt-in via `USE_LLM_NARRATOR=1` | `src/agents/narrator_agent.py` |

### Orchestration Flow

```
User Command (text / voice / web UI)
        │
        ▼
  ┌─────────────┐
  │ Orchestrator │  ← Microsoft Agent Framework
  └──────┬──────┘
         │
    ┌────┴────┐
    ▼         ▼
Planner    Narrator
 Agent      Agent
    │         │
    ▼         │
 Safety       │
 Agent        │
    │         │
    ▼         ▼
Executor   (scene
 Agent     summary)
    │
    ▼
 PyBullet
```

### Adding a new agent

1. Create a new module in `src/agents/` following the pattern in existing agents.
2. The agent must expose an async `run()` method that accepts a context dict.
3. Register it in `src/agents/orchestrator.py`.
4. If the agent produces actions, add corresponding schema entries in
   `src/brain/action_schema.py` and handlers in `src/executor/action_executor.py`.
5. Add tests in `tests/`.

### Agent-to-agent communication

Agents share state through the orchestrator's **context dict**:
- `command` – the original user text
- `plan` – the JSON action list (set by PlannerAgent)
- `validation` – safety check result (set by SafetyAgent)
- `results` – execution results (set by ExecutorAgent)
- `narration` – human-readable summary (set by NarratorAgent)

## Web UI

The web interface is served by **FastAPI** (`src/web_ui.py`):

- `GET /` – serves the single-page app from `src/static/`
- `GET /api/health` – readiness probe (200 when ready, 503 during startup)
- `GET /api/scene` – returns current scene state (objects, EE pose)
- `GET /api/models` – returns model catalog with status (always 200)
- `POST /api/command` – accepts a text command (returns 202 immediately;
  pipeline runs async, results stream via WebSocket `command_done` message)
- `POST /api/voice` – receive WAV audio, transcribe via Whisper, return text
- `POST /api/model/switch` – switch to a different model (async via WS)
- `GET /api/camera` – returns a JPEG snapshot from PyBullet's virtual camera
- `WS /ws` – WebSocket for real-time updates (plan steps, execution progress,
  camera frames, agent status, model progress)

### Voice Input

The web UI supports voice input via the microphone button (hold-to-record):

1. Browser captures audio via `MediaRecorder` API (WebM/Opus).
2. Client-side converts to 16 kHz mono WAV using `OfflineAudioContext`.
3. WAV is posted to `POST /api/voice` as multipart form data.
4. Server transcribes via Foundry Local Whisper (`src/input/voice_input.py`).
5. Whisper can only handle **30-second segments**.  For longer audio,
   `transcribe_with_chunking()` splits into ≤30 s chunks and concatenates.
6. Transcribed text is sent through the normal command pipeline.

### Workspace Bounds

The Panda robot base is at the origin `[0, 0, 0]`.  Workspace bounds cover
the full reachable envelope (`±0.855 m` in X/Y, `0–1.19 m` in Z) so that
360° rotation sweeps are not rejected by the safety agent.

### Running with web UI

```bash
python -m src.app --web          # starts FastAPI on http://localhost:8080
python -m src.app --web --no-gui # headless (no PyBullet window, web only)
```

## Testing

Tests use `pytest` and live in `tests/`. Run them with:

```bash
python -m pytest tests/ -v
```

Tests should not require a running Foundry Local instance or PyBullet GUI.
Mock external dependencies (Foundry client, PyBullet) where needed.

## Common Tasks

### Adding a new robot action

1. Add the tool schema to `TOOL_SCHEMAS` in `src/brain/action_schema.py`.
2. Add a `_do_<tool>` method in `src/executor/action_executor.py`.
3. Register it in `ActionExecutor._dispatch`.
4. Add a test in `tests/test_executor.py`.

### Changing the LLM prompt

Edit `SYSTEM_PROMPT` in `src/brain/planner.py`. Keep the response-format
section in sync with `action_schema.py`.

### Adding a new scene object

Modify `Scene.build_default()` in `src/simulation/scene.py`.

## Style & Quality

- Follow PEP 8. Use type hints on all public functions.
- Keep modules focused – one responsibility per file.
- Prefer explicit imports over star imports.
- Do not add large new dependencies without justification.

## Performance & Real-Time Requirements

The system targets **< 30 s end-to-end** for each command.  The critical
path is LLM inference; model choice dominates latency.

### Model Speed Guide

| Model | Params | Inference | Total Pipeline | Recommended For |
|---|---|---|---|---|
| `qwen2.5-coder-0.5b` | 0.5 B | ~4 s | **~5 s** | Fast interactive use |
| `phi-4-mini` | 3.6 B | ~35 s | ~36 s | Better accuracy, slower |
| `qwen2.5-coder-7b` | 7 B | ~45 s | ~46 s | Best accuracy, slowest |

Use the **model dropdown** in the web UI or `--model` CLI flag to switch.
For fastest responses, select `qwen2.5-coder-0.5b`.

### Latency Budgets

| Operation | Target | Notes |
|---|---|---|
| `/api/command` HTTP response | < 50 ms | Returns 202 immediately; pipeline runs async |
| Planner LLM call | 4–45 s | Depends on model size; `max_tokens=128` |
| Safety + Executor | < 2 s | No LLM call; pure validation + PyBullet IK |
| Narrator | < 1 ms | Template fallback (no LLM); opt-in via `USE_LLM_NARRATOR=1` |
| `/api/models` response | < 50 ms | Cached via 30 s TTL; pre-warmed at startup |
| `/api/camera` JPEG encode | < 30 ms | Pre-computed view/proj matrices, PIL `optimize=False` |
| Camera refresh in UI | ~4 fps (250 ms) | Non-blocking; skips if previous frame still loading |
| Whisper transcription | 5–30 s | ONNX pipeline cached after first call; use `whisper-small` for speed |
| WebSocket broadcast | < 5 ms | Fire-and-forget; dead clients pruned automatically |

### Key Performance Patterns

- **Async command pipeline** – `POST /api/command` returns 202 immediately.
  The pipeline runs via `asyncio.create_task()`; results stream to the
  frontend via WebSocket `command_done` messages.  No fetch timeouts.
- **Narrator fast-path** – The narrator uses an instant template by default
  (< 1 ms) instead of a second LLM call.  Set `USE_LLM_NARRATOR=1` to
  opt into LLM-generated narration.
- **Compact planner prompt** – The system prompt is 5 lines (not 15).
  `max_tokens=128` and `MAX_RETRIES=1` to minimise LLM round-trips.
- **Whisper pipeline caching** – ONNX sessions, tokenizer, and feature
  extractor are loaded once and reused across requests.  The pipeline is
  pre-warmed at server startup.  Decoder capped at 128 tokens (robot
  commands are short).
- **TTL caching** – `FoundryClient._catalog_cache` avoids redundant SDK
  round-trips.  Invalidated on model switch.
- **Pre-warm at startup** – `start_web_server()` calls `get_catalog_models()`
  and `_get_whisper_pipeline()` before `uvicorn.run()`.
- **Parallel SDK calls** – catalog, cached, and loaded model lists fetched
  concurrently via `ThreadPoolExecutor`.
- **Streaming chat** – `stream=True` with chunk collection; falls back to
  non-streaming if the endpoint doesn't support it.
- **Camera deduplication** – Frontend skips frame requests while a previous
  one is in-flight to avoid request pile-up.
- **Pre-computed camera matrices** – View and projection matrices computed
  once and reused across all frames.

### Resilience Patterns

- **Always-200 model endpoint** – `/api/models` never returns 503.  When
  the client isn't ready it returns `{"models": [], "ready": false}`.
- **Frontend retry with backoff** – `fetchModels()` retries up to 5 times
  with 2 s × attempt delays and 20 s per-request timeouts.
- **WebSocket-triggered refresh** – When the WS connects (server is ready),
  the frontend auto-fetches models if the list is empty.
- **Click-to-retry** – If all retries fail, the dropdown becomes clickable
  to manually re-trigger `fetchModels()`.
- **Stale-cache fallback** – If a catalog refresh fails, the previous cached
  result is served rather than returning an empty list.
- **Lightweight manager fallback** – `_ensure_manager()` creates a
  `FoundryLocalManager(bootstrap=False)` on-demand if the main SDK init
  fell back to env-based initialisation.

## Foundry Local SDK Integration

The project uses the **Foundry Local** Python SDK (`foundry-local` package
from https://foundrylocal.ai).  Key API surface:

```python
from foundry_local import FoundryLocalManager

# Full bootstrap (downloads + loads model) — ~3 s
manager = FoundryLocalManager("model-alias")

# Lightweight (no model loading) — ~0.8 s
manager = FoundryLocalManager(bootstrap=False)

# Properties
manager.endpoint   # str – OpenAI-compatible base URL
manager.api_key    # str – API key for the local endpoint

# Model management
manager.list_catalog_models()  # list of catalog model objects
manager.list_cached_models()   # list of locally-downloaded models
manager.list_loaded_models()   # list of currently-loaded models
manager.get_model_info(alias)  # model info or None
manager.download_model(alias)  # download to local cache
manager.load_model(alias, ttl=3600)  # load into GPU/CPU
```

### Voice / Whisper Conventions

- The mic button (🎤) is **hidden by default** and only shown when a
  Whisper model is cached or loaded (`updateMicVisibility()` in `app.js`).
- Whisper models are **filtered out** of the chat model dropdown — they
  are audio-only, not selectable as the LLM brain.
- The ONNX pipeline (encoder/decoder sessions, tokenizer, feature
  extractor) is cached in `_whisper_cache` after the first transcription.
  It is pre-warmed at server startup via `_get_whisper_pipeline()`.
- Decoder iterations are capped at **128 tokens** (robot commands are short).
- Audio > 30 s is automatically chunked into ≤30 s segments.
- `python-multipart` is required for the `/api/voice` multipart upload.

### Conventions

- Always use `bootstrap=False` for catalog-only queries to avoid the 3 s
  bootstrap penalty.
- Access the SDK via `FoundryClient._ensure_manager()`, never create a
  bare `FoundryLocalManager` elsewhere.
- Wrap SDK calls in try/except; return cached/empty results on failure.
- Use `getattr(model, "field", default)` for optional SDK model fields to
  survive API changes between SDK versions.
