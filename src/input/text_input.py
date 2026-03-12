"""Text input handler – interactive CLI prompt loop."""

from __future__ import annotations

from typing import Optional


def get_text_command() -> Optional[str]:
    """Block until the user types a command. Returns None on EOF / quit."""
    try:
        text = input("\n🤖 Enter command (or 'quit'): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if text.lower() in ("quit", "exit", "q"):
        return None
    return text if text else None
