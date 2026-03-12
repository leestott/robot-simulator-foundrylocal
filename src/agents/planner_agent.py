"""Planner Agent – translates natural-language commands into JSON action plans."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.brain.planner import Planner


class PlannerAgent:
    """Agent that converts user text into a validated action plan via the LLM."""

    name = "PlannerAgent"

    def __init__(self, planner: Planner) -> None:
        self._planner = planner

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Produce an action plan from ``context["command"]``.

        Sets ``context["plan"]`` to the list of actions, or ``None`` on failure.
        """
        command: str = context.get("command", "")
        if not command.strip():
            context["plan"] = None
            return context

        plan = await asyncio.to_thread(self._planner.plan, command)
        context["plan"] = plan
        return context
