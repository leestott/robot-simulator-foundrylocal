"""Narrator Agent – describes scene state and explains what happened."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from src.brain.foundry_client import FoundryClient
from src.simulation.scene import Scene
from src.simulation.robot import PandaRobot

NARRATOR_PROMPT = """\
You are a concise robot-scene narrator.  Given the user's command, the action
plan that was executed, and the results, write ONE short paragraph (2-4 sentences)
explaining what the robot did and the current state of the scene.
Be specific about object names and positions.  Do NOT use markdown.
"""


class NarratorAgent:
    """Agent that produces a human-readable summary of what happened."""

    name = "NarratorAgent"

    def __init__(
        self,
        client: FoundryClient,
        scene: Scene,
        robot: PandaRobot,
    ) -> None:
        self._client = client
        self._scene = scene
        self._robot = robot

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate ``context["narration"]`` from the pipeline results.

        Uses a fast template to avoid a second LLM round-trip.
        The LLM narrator can be enabled by setting USE_LLM_NARRATOR=1.
        """
        command = context.get("command", "")
        results = context.get("results", [])

        # Fast path: template narration (< 1 ms, no LLM call)
        import os
        if not os.environ.get("USE_LLM_NARRATOR"):
            context["narration"] = self._fallback_narration(command, results)
            return context

        # Slow path: LLM narration (opt-in)
        plan = context.get("plan")
        scene_desc = self._scene.describe()
        ee_pos, _ = self._robot.get_ee_pose()
        user_content = (
            f'Command: "{command}" Plan: {plan} Results: {results} '
            f'EE at {[round(v, 3) for v in ee_pos]}.'
        )
        messages = [
            {"role": "system", "content": NARRATOR_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            narration = await asyncio.wait_for(
                asyncio.to_thread(self._client.chat, messages, None, 64),
                timeout=15.0,
            )
        except Exception:
            narration = None
        if narration is None:
            narration = self._fallback_narration(command, results)

        context["narration"] = narration
        return context

    @staticmethod
    def _fallback_narration(
        command: str, results: List[Dict[str, Any]]
    ) -> str:
        """Simple template narration when the LLM is unavailable."""
        ok = sum(1 for r in results if r.get("status") == "ok")
        total = len(results)
        if total == 0:
            return f"Received command \"{command}\" but no actions were executed."
        return (
            f"Executed {ok}/{total} action(s) for command \"{command}\". "
            f"{'All steps succeeded.' if ok == total else 'Some steps failed.'}"
        )
