# Building a Voice-Controlled Robot Simulator with On-Device AI

*A practical guide for AI engineers and developers using Foundry Local,
the Microsoft Agent Framework, and PyBullet — no cloud, no API keys.*

![Robot Arm Simulator Architecture](https://raw.githubusercontent.com/leestott/robot-simulator-foundrylocal/main/docs/screenshots/architecture.png)

---

## Why This Matters

Most AI demos send every request to a cloud API. That means latency,
costs, and data leaving your machine. **Foundry Local** changes the
equation: you get an OpenAI-compatible endpoint running entirely
on-device. Pair it with a multi-agent framework and a physics simulator,
and you have a complete voice-to-action pipeline with zero cloud
dependencies.

This post walks through how we built it — and the patterns you can
reuse in your own on-device AI applications.

---

## Architecture

The system uses four specialised agents orchestrated by the
**Microsoft Agent Framework**:

```
  User (text / voice)
        │
        ▼
  ┌─────────────┐
  │ Orchestrator │
  └──────┬──────┘
         │
    ┌────┴────┐
    ▼         ▼
 Planner   Narrator
  Agent     Agent
    │         │
    ▼         │
  Safety      │
  Agent       │
    │         │
    ▼         ▼
 Executor  (scene
  Agent    summary)
    │
    ▼
  PyBullet
```

| Agent | What It Does | Speed |
|---|---|---|
| **PlannerAgent** | Sends user command to Foundry Local LLM → JSON action plan | 4–45 s (model-dependent) |
| **SafetyAgent** | Validates against workspace bounds + schema | < 1 ms |
| **ExecutorAgent** | Dispatches actions to PyBullet (IK, gripper) | < 2 s |
| **NarratorAgent** | Template summary (LLM opt-in via env var) | < 1 ms |

---

## Setting Up Foundry Local

```python
from foundry_local import FoundryLocalManager
import openai

# Downloads + loads the model (~16 s first time, ~3 s after)
manager = FoundryLocalManager("qwen2.5-coder-0.5b")

# Standard OpenAI client — zero code changes from cloud
client = openai.OpenAI(
    base_url=manager.endpoint,
    api_key=manager.api_key,
)

resp = client.chat.completions.create(
    model=manager.get_model_info("qwen2.5-coder-0.5b").id,
    messages=[{"role": "user", "content": "pick up the cube"}],
    max_tokens=128,
    stream=True,
)
```

The SDK auto-selects the best hardware backend (CUDA GPU → QNN NPU → CPU).
No configuration needed.

---

## The Multi-Agent Pipeline

Instead of one monolithic prompt, we split the task across four agents.
Each has a single responsibility and communicates via a shared context dict.

### PlannerAgent — NL → JSON

The planner sends the user's command to the LLM with a **compact 5-line
system prompt** and strict JSON schema:

```json
{
  "type": "plan",
  "actions": [
    {"tool": "describe_scene", "args": {}},
    {"tool": "pick", "args": {"object": "cube_1"}}
  ]
}
```

Key decisions:
- `max_tokens=128` — robot JSON plans are small
- `MAX_RETRIES=1` — one correction attempt if the LLM returns bad JSON
- `stream=True` — faster first-token latency

### SafetyAgent — Validation

Checks every action against:
- **Allowed tools** — only 7 tools in the schema
- **Workspace bounds** — Panda arm reaches ±0.855 m (X/Y), 0–1.19 m (Z)
- **Required arguments** — e.g. `pick` needs an `object` name

If validation fails, the executor is skipped and the narrator explains why.

### ExecutorAgent — PyBullet Dispatch

Maps validated actions to simulation calls:
- `move_ee` → inverse kinematics + joint interpolation
- `pick` → approach → descend → close gripper → lift
- `place` → move to target → open gripper

### NarratorAgent — Fast Feedback

Uses an **instant template** by default (< 1 ms) instead of a second
LLM call. Set `USE_LLM_NARRATOR=1` to opt into richer narration.

---

## Adding Voice Input

![Voice Pipeline](https://raw.githubusercontent.com/leestott/robot-simulator-foundrylocal/main/docs/screenshots/voice_pipeline.png)

Voice commands follow three stages:

### 1. Browser Capture

The web UI uses `MediaRecorder` to capture audio, then resamples to
**16 kHz mono WAV** client-side using `OfflineAudioContext`:

```javascript
const offCtx = new OfflineAudioContext(1, Math.ceil(duration * 16000), 16000);
const src = offCtx.createBufferSource();
src.buffer = audioBuf;
src.connect(offCtx.destination);
src.start();
const rendered = await offCtx.startRendering();
```

### 2. Server Transcription (Whisper ONNX)

The `/api/voice` endpoint transcribes via Foundry Local's Whisper model.
The ONNX pipeline is **cached after first load** and supports both
fp16 (CUDA) and fp32 (CPU) model variants automatically:

```python
def transcribe_with_chunking(wav_path, whisper_alias, max_chunk_seconds=30):
    audio, sr = librosa.load(wav_path, sr=16000)
    if len(audio) / sr <= max_chunk_seconds:
        return transcribe_audio_foundry(wav_path, whisper_alias)
    # Split into ≤30 s chunks for Whisper's segment limit
    chunks = [audio[i:i+chunk_samples] for i in range(0, len(audio), chunk_samples)]
    return " ".join(transcribe_audio_foundry(chunk, whisper_alias) for chunk in chunks)
```

### 3. Command Execution

Transcribed text goes through the same agent pipeline as typed commands.
The mic button only appears when a Whisper model is cached/loaded.

---

## Real-Time Web UI

| Live Camera | Commands | Agent Pipeline |
|---|---|---|
| ![App Pick](https://raw.githubusercontent.com/leestott/robot-simulator-foundrylocal/main/docs/screenshots/app_pick.png) | ![App Describe](https://raw.githubusercontent.com/leestott/robot-simulator-foundrylocal/main/docs/screenshots/app_describe.png) | ![App Move](https://raw.githubusercontent.com/leestott/robot-simulator-foundrylocal/main/docs/screenshots/app_move.png) |

The web UI uses a **fire-and-forget** pattern:

1. `POST /api/command` returns **202 Accepted** immediately
2. Pipeline runs via `asyncio.create_task()`
3. Each agent step broadcasts via WebSocket
4. `command_done` message delivers final results

This eliminates browser fetch timeouts — even when LLM inference
takes 30+ seconds on slower models.

---

## Performance: Model Choice Matters

The single biggest factor in latency is **model size**:

| Model | Params | Inference | Pipeline Total |
|---|---|---|---|
| `qwen2.5-coder-0.5b` | 0.5 B | **~4 s** | **~5 s** |
| `phi-4-mini` | 3.6 B | ~35 s | ~36 s |
| `qwen2.5-coder-7b` | 7 B | ~45 s | ~46 s |

For interactive robot control, `qwen2.5-coder-0.5b` is the clear
winner. The 0.5B model produces valid JSON action plans reliably enough
for the constrained 7-tool schema.

### Other Performance Patterns

- **Narrator fast-path** — template instead of LLM (saves ~35 s)
- **Whisper pipeline caching** — ONNX sessions loaded once, reused
- **TTL catalog cache** — 30 s cache on model listings
- **Pre-warm at startup** — catalog + Whisper loaded before first request
- **Camera deduplication** — skips frames while previous is in-flight

---

## Getting Started

```bash
# 1. Install Foundry Local
winget install Microsoft.FoundryLocal    # Windows
brew install foundrylocal                # macOS

# 2. Download models
foundry model run qwen2.5-coder-0.5b    # Chat brain (~4 s inference)
foundry model run whisper-base           # Voice input (194 MB)

# 3. Clone & setup
git clone https://github.com/leestott/robot-simulator-foundrylocal
cd robot-simulator-foundrylocal
.\setup.ps1                              # or ./setup.sh on macOS/Linux

# 4. Run
python -m src.app --web --no-gui         # → http://localhost:8080
```

Try these commands:
- **"pick up the cube"** — robot picks up the blue cube
- **"describe the scene"** — lists all objects and positions
- **"reset"** — returns to neutral pose

---

## Extending It

### Add a new robot action

1. Add schema to `TOOL_SCHEMAS` in `src/brain/action_schema.py`
2. Add handler `_do_<tool>` in `src/executor/action_executor.py`
3. Register in `ActionExecutor._dispatch`
4. Add a test

### Add a new agent

1. Create `src/agents/my_agent.py` with `async run(context)`
2. Register in `src/agents/orchestrator.py`

### Swap the LLM

```bash
python -m src.app --web --model phi-4-mini
```

Or use the model dropdown in the web UI — no restart needed.

---

## Key Takeaways

1. **On-device AI is production-ready.** Foundry Local serves models via
   a standard OpenAI API. Swap `base_url` and you're done.

2. **Multi-agent beats monolithic.** Four focused agents with JSON schema
   contracts are more reliable than one prompt trying to do everything.

3. **Voice is just another input.** Same pipeline for text and speech —
   the only difference is the Whisper transcription step.

4. **Model size drives latency.** A 0.5B model at ~4 s is 10× faster
   than a 7B model at ~45 s. For constrained schemas, smaller models
   produce valid output reliably.

5. **Async-first for real-time.** `asyncio.create_task` + WebSocket
   keeps the UI responsive during inference.

---

*Source code: [github.com/leestott/robot-simulator-foundrylocal](https://github.com/leestott/robot-simulator-foundrylocal)*

*Built with [Foundry Local](https://foundrylocal.ai),
[Microsoft Agent Framework](https://github.com/microsoft/agents),
[PyBullet](https://pybullet.org), and
[FastAPI](https://fastapi.tiangolo.com).*
