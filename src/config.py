"""Centralised configuration for the robot-simulator project."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Runtime configuration – populated from CLI args + env vars."""

    # ── Foundry Local ────────────────────────────────────────────────
    foundry_base_url: str = ""  # filled at runtime via SDK or env
    foundry_model_alias: str = "qwen2.5-coder-0.5b"
    whisper_model_alias: str = "whisper-tiny"
    api_key: str = "not-required"
    max_completion_tokens: int = 128
    temperature: float = 0.1

    # ── Simulation ───────────────────────────────────────────────────
    target_object_path: Optional[str] = None  # path to OBJ/STL/URDF
    use_gui: bool = True
    time_step: float = 1.0 / 240.0

    # ── Input mode ───────────────────────────────────────────────────
    input_mode: str = "text"  # "text" or "voice"
    voice_record_seconds: float = 5.0

    # ── Web UI ───────────────────────────────────────────────────────
    web: bool = False
    web_port: int = 8080

    # ── Misc ─────────────────────────────────────────────────────────
    dry_run: bool = False
    verbose: bool = False

    # ── Workspace bounds (metres, world frame) ───────────────────────
    # Covers the Panda robot's full reachable workspace including
    # positions near the base (needed for 360° rotation sweeps).
    ws_x_min: float = -0.855
    ws_x_max: float = 0.855
    ws_y_min: float = -0.855
    ws_y_max: float = 0.855
    ws_z_min: float = 0.0
    ws_z_max: float = 1.19


def parse_args() -> Config:
    """Build a Config from CLI arguments and environment variables."""
    p = argparse.ArgumentParser(
        description="Robot-arm simulator controlled by Foundry Local LLM"
    )

    p.add_argument(
        "--mode",
        choices=["text", "voice"],
        default=os.getenv("INPUT_MODE", "text"),
        help="Input modality (default: text)",
    )
    p.add_argument(
        "--model",
        default=os.getenv("FOUNDRY_MODEL", "qwen2.5-coder-0.5b"),
        help="Foundry Local model alias for the chat brain",
    )
    p.add_argument(
        "--whisper-model",
        default=os.getenv("FOUNDRY_WHISPER_MODEL", "whisper-tiny"),
        help="Foundry Local Whisper model alias for voice transcription",
    )
    p.add_argument(
        "--object",
        default=None,
        help="Path to a custom target object (OBJ / STL / URDF)",
    )
    p.add_argument(
        "--record-seconds",
        type=float,
        default=5.0,
        help="Seconds to record for voice mode (default: 5)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without executing them",
    )
    p.add_argument(
        "--no-gui",
        action="store_true",
        help="Run PyBullet in DIRECT mode (headless, no GUI)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="Launch the FastAPI web UI instead of the CLI loop",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("WEB_PORT", "8080")),
        help="Port for the web UI (default: 8080)",
    )

    args = p.parse_args()

    cfg = Config(
        input_mode=args.mode,
        foundry_model_alias=args.model,
        whisper_model_alias=args.whisper_model,
        target_object_path=args.object,
        voice_record_seconds=args.record_seconds,
        dry_run=args.dry_run,
        use_gui=not args.no_gui,
        verbose=args.verbose,
        web=args.web,
        web_port=args.port,
    )

    # Allow overriding the base URL from env (fallback; SDK discovery preferred)
    env_url = os.getenv("FOUNDRY_LOCAL_BASE_URL", "")
    if env_url:
        cfg.foundry_base_url = env_url.rstrip("/")

    return cfg
