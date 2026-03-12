"""Tests for ActionExecutor – dry-run mode and dispatch logic."""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Mock heavy native deps before imports
for mod in ("pybullet", "pybullet_data"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

from src.executor.action_executor import ActionExecutor


def _make_executor(dry_run: bool = False) -> ActionExecutor:
    """Build an executor with mocked dependencies."""
    robot = MagicMock()
    scene = MagicMock()
    grasp = MagicMock()
    robot.get_ee_pose.return_value = ([0.5, 0.0, 0.5], [3.14, 0.0, 0.0])
    return ActionExecutor(robot=robot, scene=scene, grasp=grasp, dry_run=dry_run)


class TestDryRun(unittest.TestCase):
    """In dry-run mode, no simulation calls should be made."""

    def test_single_action_dry_run(self):
        ex = _make_executor(dry_run=True)
        actions = [{"tool": "reset", "args": {}}]
        results = ex.execute_plan(actions)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "dry-run")

    def test_multi_action_dry_run(self):
        ex = _make_executor(dry_run=True)
        actions = [
            {"tool": "open_gripper", "args": {"width": 0.04}},
            {"tool": "move_ee", "args": {"target_xyz": [0.5, 0.0, 0.5]}},
            {"tool": "close_gripper", "args": {"force": 40.0}},
        ]
        results = ex.execute_plan(actions)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["status"] == "dry-run" for r in results))


class TestDispatch(unittest.TestCase):
    """Real dispatch (non-dry-run) should call the right mock methods."""

    def test_reset_calls_robot(self):
        ex = _make_executor()
        ex.execute_plan([{"tool": "reset", "args": {}}])
        ex._robot.reset.assert_called_once()

    def test_open_gripper(self):
        ex = _make_executor()
        ex.execute_plan([{"tool": "open_gripper", "args": {"width": 0.03}}])
        ex._robot.open_gripper.assert_called_once_with(width=0.03)

    def test_close_gripper(self):
        ex = _make_executor()
        ex.execute_plan([{"tool": "close_gripper", "args": {"force": 50.0}}])
        ex._robot.close_gripper.assert_called_once_with(force=50.0)

    def test_move_ee(self):
        ex = _make_executor()
        ex._robot.move_ee.return_value = True
        ex.execute_plan([{"tool": "move_ee", "args": {"target_xyz": [0.3, 0.1, 0.5]}}])
        ex._robot.move_ee.assert_called_once()
        call_kwargs = ex._robot.move_ee.call_args
        self.assertEqual(call_kwargs.kwargs["target_xyz"], [0.3, 0.1, 0.5])

    def test_describe_scene(self):
        ex = _make_executor()
        ex._scene.describe.return_value = [{"name": "cube_1", "position": [0.5, 0, 0.65]}]
        results = ex.execute_plan([{"tool": "describe_scene", "args": {}}])
        self.assertEqual(results[0]["status"], "ok")
        self.assertIn("objects", results[0]["result"])

    def test_pick_existing_object(self):
        ex = _make_executor()
        ex._scene.objects = {"cube_1": MagicMock()}
        ex._grasp.pick.return_value = True
        results = ex.execute_plan([{"tool": "pick", "args": {"object": "cube_1"}}])
        ex._grasp.pick.assert_called_once_with("cube_1")
        self.assertTrue(results[0]["result"]["success"])

    def test_pick_fuzzy_match(self):
        ex = _make_executor()
        ex._scene.objects = {"cube_1": MagicMock()}
        ex._scene.find_object_by_substring.return_value = "cube_1"
        ex._grasp.pick.return_value = True
        results = ex.execute_plan([{"tool": "pick", "args": {"object": "cube"}}])
        ex._grasp.pick.assert_called_once_with("cube_1")

    def test_pick_object_not_found(self):
        ex = _make_executor()
        ex._scene.objects = {}
        ex._scene.find_object_by_substring.return_value = None
        results = ex.execute_plan([{"tool": "pick", "args": {"object": "banana"}}])
        self.assertFalse(results[0]["result"]["success"])

    def test_place(self):
        ex = _make_executor()
        ex._grasp.place.return_value = True
        results = ex.execute_plan([{"tool": "place", "args": {"target_xyz": [0.3, 0.2, 0.65]}}])
        ex._grasp.place.assert_called_once_with([0.3, 0.2, 0.65])

    def test_unknown_tool(self):
        ex = _make_executor()
        results = ex.execute_plan([{"tool": "fly_away", "args": {}}])
        self.assertIn("error", results[0]["result"])


if __name__ == "__main__":
    unittest.main()
