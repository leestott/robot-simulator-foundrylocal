"""Orchestrator – coordinates the multi-agent pipeline.

Flow:  command → PlannerAgent → SafetyAgent → ExecutorAgent → NarratorAgent
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional

from src.agents.planner_agent import PlannerAgent
from src.agents.safety_agent import SafetyAgent
from src.agents.executor_agent import ExecutorAgent
from src.agents.narrator_agent import NarratorAgent
from src.brain.foundry_client import FoundryClient
from src.brain.planner import Planner
from src.config import Config
from src.executor.action_executor import ActionExecutor
from src.simulation.robot import PandaRobot
from src.simulation.scene import Scene


class Orchestrator:
    """Runs the agent pipeline for a single user command."""

    def __init__(
        self,
        config: Config,
        planner: Planner,
        executor: ActionExecutor,
        client: FoundryClient,
        scene: Scene,
        robot: PandaRobot,
    ) -> None:
        self._agents: List = [
            PlannerAgent(planner),
            SafetyAgent(config),
            ExecutorAgent(executor),
            NarratorAgent(client, scene, robot),
        ]
        self._on_step: Optional[Callable] = None

    def set_step_callback(self, callback: Callable) -> None:
        """Register a callback invoked after each agent runs.

        Signature: ``callback(agent_name: str, context: dict)``
        """
        self._on_step = callback

    async def handle_command(self, command: str) -> Dict[str, Any]:
        """Run *command* through the full agent pipeline.

        Returns the final context dict containing plan, validation,
        results, and narration.
        """
        context: Dict[str, Any] = {"command": command}

        for agent in self._agents:
            context = await agent.run(context)
            if self._on_step:
                try:
                    ret = self._on_step(agent.name, context)
                    if inspect.isawaitable(ret):
                        await ret
                except Exception:
                    pass

            # Short-circuit: if safety rejected the plan, skip executor
            if agent.name == "SafetyAgent":
                validation = context.get("validation", {})
                if not validation.get("valid"):
                    # Still run narrator so the user gets feedback
                    context = await self._agents[-1].run(context)
                    if self._on_step:
                        try:
                            ret = self._on_step(self._agents[-1].name, context)
                            if inspect.isawaitable(ret):
                                await ret
                        except Exception:
                            pass
                    break

        return context

    def handle_command_sync(self, command: str) -> Dict[str, Any]:
        """Synchronous wrapper around :meth:`handle_command`."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, self.handle_command(command)
                ).result()
        return asyncio.run(self.handle_command(command))
