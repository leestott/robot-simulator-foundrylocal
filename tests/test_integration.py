"""Integration test – runs the full pipeline against a live Foundry Local model.

Usage:
    python tests/test_integration.py

Requires:
    - Foundry Local service running
    - phi-4-mini model available
    - PyBullet installed

Note: This is a standalone script, NOT a pytest module.
      Run it directly: python tests/test_integration.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pybullet as p
from src.config import Config
from src.simulation.scene import Scene
from src.simulation.robot import PandaRobot
from src.simulation.grasp import GraspController
from src.brain.foundry_client import FoundryClient
from src.brain.planner import Planner
from src.executor.action_executor import ActionExecutor

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"


def _setup():
    """Boot simulation + connect to Foundry Local."""
    cfg = Config()
    cfg.use_gui = False

    # Simulation
    cid = p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)

    scene = Scene(cid)
    scene.build_default()

    robot = PandaRobot(cid)
    grasp = GraspController(robot, scene, cid)

    # Settle
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)

    # LLM
    client = FoundryClient(cfg)
    ok = client.initialise()
    if not ok:
        print(f"{FAIL} Cannot connect to Foundry Local – is the service running?")
        p.disconnect(cid)
        sys.exit(1)

    planner = Planner(client, scene)
    executor = ActionExecutor(robot, scene, grasp, dry_run=False)

    return cid, scene, robot, planner, executor


def test_describe_scene(planner, executor):
    """LLM should return a describe_scene action."""
    print("\n--- Test: describe the scene ---")
    actions = planner.plan("describe the scene")
    if actions is None:
        print(f"  {FAIL} Planner returned None")
        return False

    print(f"  Plan: {actions}")
    tools = [a["tool"] for a in actions]
    if "describe_scene" not in tools:
        print(f"  {FAIL} Expected describe_scene in plan, got {tools}")
        return False

    results = executor.execute_plan(actions)
    print(f"  Results: {results}")

    # Check result contains scene data
    for r in results:
        if r["tool"] == "describe_scene":
            detail = r.get("result", {})
            if isinstance(detail, dict) and "objects" in detail:
                print(f"  {PASS} describe_scene returned {len(detail['objects'])} objects")
                return True

    print(f"  {FAIL} describe_scene did not return expected data")
    return False


def test_pick_cube(planner, executor):
    """LLM should generate a pick action for the cube."""
    print("\n--- Test: pick up the cube ---")
    actions = planner.plan("pick up the cube")
    if actions is None:
        print(f"  {FAIL} Planner returned None")
        return False

    print(f"  Plan: {actions}")
    tools = [a["tool"] for a in actions]
    if "pick" not in tools:
        print(f"  {FAIL} Expected pick in plan, got {tools}")
        return False

    print(f"  {PASS} Planner produced pick action(s): {tools}")
    return True


def test_move_ee(planner, executor):
    """LLM should generate a move_ee action with coordinates."""
    print("\n--- Test: move to position ---")
    actions = planner.plan("move to x 0.4 y 0.1 z 0.3")
    if actions is None:
        print(f"  {FAIL} Planner returned None")
        return False

    print(f"  Plan: {actions}")
    tools = [a["tool"] for a in actions]
    if "move_ee" not in tools:
        print(f"  {FAIL} Expected move_ee in plan, got {tools}")
        return False

    # Validate the coordinates were parsed
    for a in actions:
        if a["tool"] == "move_ee":
            xyz = a["args"].get("target_xyz", [])
            print(f"  Coordinates: {xyz}")
            if len(xyz) == 3:
                print(f"  {PASS} move_ee with valid coordinates")
                return True

    print(f"  {FAIL} move_ee missing valid target_xyz")
    return False


def test_reset(planner, executor):
    """LLM should generate a reset action."""
    print("\n--- Test: reset ---")
    actions = planner.plan("reset the robot")
    if actions is None:
        print(f"  {FAIL} Planner returned None")
        return False

    print(f"  Plan: {actions}")
    tools = [a["tool"] for a in actions]
    if "reset" not in tools:
        print(f"  {FAIL} Expected reset in plan, got {tools}")
        return False

    results = executor.execute_plan(actions)
    print(f"  {PASS} reset executed successfully")
    return True


def test_voice_dependencies():
    """Check that voice mode dependencies are importable."""
    print("\n--- Test: voice mode dependencies ---")
    issues = []
    for mod in ["sounddevice", "numpy", "onnxruntime", "librosa", "transformers"]:
        try:
            __import__(mod)
        except ImportError:
            issues.append(mod)

    if issues:
        print(f"  {FAIL} Missing modules: {issues}")
        return False

    print(f"  {PASS} All voice dependencies importable")
    return True


def main():
    print("=" * 60)
    print("  Robot Simulator – Integration Test")
    print("=" * 60)

    # Voice deps check doesn't need the full setup
    results = {}
    results["voice_deps"] = test_voice_dependencies()

    cid, scene, robot, planner, executor = _setup()

    try:
        results["describe_scene"] = test_describe_scene(planner, executor)
        results["pick_cube"] = test_pick_cube(planner, executor)
        results["move_ee"] = test_move_ee(planner, executor)
        results["reset"] = test_reset(planner, executor)
    finally:
        p.disconnect(cid)

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  {PASS if ok else FAIL} {name}")
    print(f"\n  {passed}/{total} tests passed")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
