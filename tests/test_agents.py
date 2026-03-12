"""Tests for the Microsoft Agent Framework agents and orchestrator."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.agents.planner_agent import PlannerAgent
from src.agents.safety_agent import SafetyAgent
from src.agents.executor_agent import ExecutorAgent
from src.agents.narrator_agent import NarratorAgent
from src.agents.orchestrator import Orchestrator
from src.config import Config


# ── Helpers ──────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_plan():
    return [{"tool": "describe_scene", "args": {}}]


def _make_move_plan(x=0.5, y=0.0, z=0.4):
    return [{"tool": "move_ee", "args": {"target_xyz": [x, y, z]}}]


# ── PlannerAgent ─────────────────────────────────────────────────

class TestPlannerAgent:
    def test_produces_plan(self):
        mock_planner = MagicMock()
        mock_planner.plan.return_value = _make_plan()

        agent = PlannerAgent(mock_planner)
        ctx = _run(agent.run({"command": "describe the scene"}))

        assert ctx["plan"] is not None
        assert len(ctx["plan"]) == 1
        assert ctx["plan"][0]["tool"] == "describe_scene"

    def test_empty_command(self):
        mock_planner = MagicMock()
        agent = PlannerAgent(mock_planner)
        ctx = _run(agent.run({"command": ""}))
        assert ctx["plan"] is None
        mock_planner.plan.assert_not_called()

    def test_planner_failure(self):
        mock_planner = MagicMock()
        mock_planner.plan.return_value = None
        agent = PlannerAgent(mock_planner)
        ctx = _run(agent.run({"command": "do something"}))
        assert ctx["plan"] is None


# ── SafetyAgent ──────────────────────────────────────────────────

class TestSafetyAgent:
    def test_valid_plan_passes(self):
        cfg = Config()
        agent = SafetyAgent(cfg)
        ctx = _run(agent.run({"plan": _make_plan()}))
        assert ctx["validation"]["valid"] is True

    def test_no_plan_fails(self):
        cfg = Config()
        agent = SafetyAgent(cfg)
        ctx = _run(agent.run({"plan": None}))
        assert ctx["validation"]["valid"] is False

    def test_unknown_tool_rejected(self):
        cfg = Config()
        agent = SafetyAgent(cfg)
        ctx = _run(agent.run({"plan": [{"tool": "fly_away", "args": {}}]}))
        assert ctx["validation"]["valid"] is False
        assert any("unknown tool" in e for e in ctx["validation"]["errors"])

    def test_out_of_bounds_x(self):
        cfg = Config()
        agent = SafetyAgent(cfg)
        plan = _make_move_plan(x=5.0)  # way outside bounds
        ctx = _run(agent.run({"plan": plan}))
        assert ctx["validation"]["valid"] is False

    def test_in_bounds_passes(self):
        cfg = Config()
        agent = SafetyAgent(cfg)
        plan = _make_move_plan(x=0.5, y=0.0, z=0.4)
        ctx = _run(agent.run({"plan": plan}))
        assert ctx["validation"]["valid"] is True


# ── ExecutorAgent ────────────────────────────────────────────────

class TestExecutorAgent:
    def test_skips_when_validation_fails(self):
        mock_executor = MagicMock()
        agent = ExecutorAgent(mock_executor)
        ctx = _run(agent.run({
            "plan": _make_plan(),
            "validation": {"valid": False, "errors": ["boom"]},
        }))
        assert ctx["results"][0]["status"] == "skipped"
        mock_executor.execute_plan.assert_not_called()

    def test_executes_when_valid(self):
        mock_executor = MagicMock()
        mock_executor.execute_plan.return_value = [
            {"tool": "describe_scene", "status": "ok", "result": {}}
        ]
        agent = ExecutorAgent(mock_executor)
        ctx = _run(agent.run({
            "plan": _make_plan(),
            "validation": {"valid": True},
        }))
        assert ctx["results"][0]["status"] == "ok"


# ── NarratorAgent ────────────────────────────────────────────────

class TestNarratorAgent:
    def test_fallback_narration(self):
        text = NarratorAgent._fallback_narration(
            "pick up the cube",
            [{"tool": "pick", "status": "ok", "result": {}}],
        )
        assert "1/1" in text
        assert "succeeded" in text.lower()

    def test_fallback_no_actions(self):
        text = NarratorAgent._fallback_narration("hello", [])
        assert "no actions" in text.lower()

    def test_run_uses_llm(self):
        """With USE_LLM_NARRATOR=1 the agent calls the LLM."""
        import os
        mock_client = MagicMock()
        mock_client.chat.return_value = "The robot described the scene."
        mock_scene = MagicMock()
        mock_scene.describe.return_value = []
        mock_robot = MagicMock()
        mock_robot.get_ee_pose.return_value = ([0.3, 0.0, 0.5], [3.14, 0, 0])

        agent = NarratorAgent(mock_client, mock_scene, mock_robot)
        old = os.environ.get("USE_LLM_NARRATOR")
        os.environ["USE_LLM_NARRATOR"] = "1"
        try:
            ctx = _run(agent.run({
                "command": "describe",
                "plan": _make_plan(),
                "results": [{"tool": "describe_scene", "status": "ok"}],
            }))
            assert ctx["narration"] == "The robot described the scene."
        finally:
            if old is None:
                os.environ.pop("USE_LLM_NARRATOR", None)
            else:
                os.environ["USE_LLM_NARRATOR"] = old

    def test_run_fallback_when_llm_fails(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = None
        mock_scene = MagicMock()
        mock_scene.describe.return_value = []
        mock_robot = MagicMock()
        mock_robot.get_ee_pose.return_value = ([0, 0, 0], [0, 0, 0])

        agent = NarratorAgent(mock_client, mock_scene, mock_robot)
        ctx = _run(agent.run({
            "command": "test",
            "plan": None,
            "results": [],
        }))
        assert "no actions" in ctx["narration"].lower()


# ── Orchestrator ─────────────────────────────────────────────────

class TestOrchestrator:
    def _make_orchestrator(self, plan=None, chat_result="Done."):
        mock_planner = MagicMock()
        mock_planner.plan.return_value = plan

        mock_executor = MagicMock()
        mock_executor.execute_plan.return_value = [
            {"tool": "describe_scene", "status": "ok", "result": {}}
        ]

        mock_client = MagicMock()
        mock_client.chat.return_value = chat_result

        mock_scene = MagicMock()
        mock_scene.describe.return_value = []

        mock_robot = MagicMock()
        mock_robot.get_ee_pose.return_value = ([0.3, 0.0, 0.5], [3.14, 0, 0])

        cfg = Config()
        orch = Orchestrator(
            config=cfg,
            planner=mock_planner,
            executor=mock_executor,
            client=mock_client,
            scene=mock_scene,
            robot=mock_robot,
        )
        return orch

    def test_full_pipeline(self):
        orch = self._make_orchestrator(plan=_make_plan())
        result = _run(orch.handle_command("describe the scene"))
        assert result["plan"] is not None
        assert result["validation"]["valid"] is True
        assert result["results"][0]["status"] == "ok"
        assert "1/1" in result["narration"]  # template fallback

    def test_pipeline_plan_failure(self):
        orch = self._make_orchestrator(plan=None)
        result = _run(orch.handle_command("do something"))
        assert result["plan"] is None
        # Safety should flag it
        assert result["validation"]["valid"] is False

    def test_step_callback_called(self):
        orch = self._make_orchestrator(plan=_make_plan())
        steps = []
        orch.set_step_callback(lambda name, ctx: steps.append(name))
        _run(orch.handle_command("test"))
        assert "PlannerAgent" in steps
        assert "SafetyAgent" in steps
        assert "ExecutorAgent" in steps
        assert "NarratorAgent" in steps

    def test_sync_wrapper(self):
        orch = self._make_orchestrator(plan=_make_plan())
        result = orch.handle_command_sync("test")
        assert "1/1" in result["narration"]  # template fallback
