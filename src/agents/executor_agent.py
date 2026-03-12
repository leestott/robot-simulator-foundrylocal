"""Executor Agent – dispatches validated action plans to PyBullet."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from src.executor.action_executor import ActionExecutor


class ExecutorAgent:
    """Agent that runs a validated plan through the ActionExecutor."""

    name = "ExecutorAgent"

    def __init__(self, executor: ActionExecutor) -> None:
        self._executor = executor

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute ``context["plan"]`` if validation passed.

        Sets ``context["results"]`` to the list of per-action results.
        """
        validation = context.get("validation", {})
        if not validation.get("valid"):
            context["results"] = [
                {
                    "tool": "pipeline",
                    "status": "skipped",
                    "result": {"error": "plan failed validation"},
                }
            ]
            return context

        plan: List[Dict[str, Any]] = context.get("plan", [])
        results = await asyncio.to_thread(self._executor.execute_plan, plan)
        context["results"] = results
        return context
