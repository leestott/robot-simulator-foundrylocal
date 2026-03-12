"""Planner – translates natural language into validated action plans via the LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from src.brain.action_schema import TOOL_SCHEMAS, schema_prompt_block, validate_plan
from src.brain.foundry_client import FoundryClient
from src.simulation.scene import Scene

MAX_RETRIES = 1

SYSTEM_PROMPT = """\
You are a robot-arm controller. Output ONLY valid JSON — no markdown, no explanation.
Tools: move_ee(target_xyz), open_gripper(), close_gripper(), pick(object), place(target_xyz), reset(), describe_scene().
Single: {{"type":"action","tool":"pick","args":{{"object":"cube_1"}}}}
Multi:  {{"type":"plan","actions":[{{"tool":"describe_scene","args":{{}}}},{{"tool":"pick","args":{{"object":"cube_1"}}}}]}}

{schema}
"""


class Planner:
    """Converts user text into a validated list of actions."""

    def __init__(self, client: FoundryClient, scene: Scene) -> None:
        self._client = client
        self._scene = scene
        self._history: List[Dict[str, str]] = []

    def plan(self, user_text: str) -> Optional[List[Dict[str, Any]]]:
        """Return a validated action list for *user_text*, or None."""
        system = SYSTEM_PROMPT.format(schema=schema_prompt_block())

        messages = [
            {"role": "system", "content": system},
            *self._history[-6:],  # keep context brief
            {"role": "user", "content": user_text},
        ]

        for attempt in range(1, MAX_RETRIES + 2):
            raw = self._client.chat(messages, max_tokens=128)
            if raw is None:
                return None

            # Try to extract JSON from the response
            json_str = self._extract_json(raw)
            if json_str is None:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. "
                            "Reply with ONLY a JSON object using the schema above."
                        ),
                    },
                )
                continue

            actions = validate_plan(json_str)
            if actions is not None:
                self._history.append({"role": "user", "content": user_text})
                self._history.append({"role": "assistant", "content": raw})
                return actions

            # Validation failed – ask LLM to fix
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The JSON was invalid or contained unknown tools/args. "
                        "Fix it and reply with ONLY valid JSON."
                    ),
                },
            )

        print("[planner] could not produce a valid plan after retries")
        return None

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Best-effort extraction of a JSON object from *text*."""
        # Try the whole string first
        text = text.strip()
        if text.startswith("{"):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                pass

        # Try to find a JSON block inside markdown fences
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                json.loads(m.group(1))
                return m.group(1)
            except json.JSONDecodeError:
                pass

        # Find the first { ... } substring
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start : i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        start = None
        return None
