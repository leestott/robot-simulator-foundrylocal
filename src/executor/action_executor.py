"""Action executor – maps validated action dicts to simulation calls."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.simulation.grasp import GraspController
from src.simulation.robot import PandaRobot
from src.simulation.scene import Scene


class ActionExecutor:
    """Executes validated action plans against the simulation."""

    def __init__(
        self,
        robot: PandaRobot,
        scene: Scene,
        grasp: GraspController,
        dry_run: bool = False,
    ) -> None:
        self._robot = robot
        self._scene = scene
        self._grasp = grasp
        self._dry_run = dry_run

    def execute_plan(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute each action in order. Returns a list of result dicts."""
        results: List[Dict[str, Any]] = []
        for i, act in enumerate(actions):
            tool = act["tool"]
            args = act["args"]
            print(f"  [{i+1}/{len(actions)}] {tool}({json.dumps(args)})")

            if self._dry_run:
                results.append({"tool": tool, "status": "dry-run", "result": None})
                continue

            result = self._dispatch(tool, args)
            results.append({"tool": tool, "status": "ok", "result": result})
        return results

    def _dispatch(self, tool: str, args: Dict[str, Any]) -> Any:
        handler = {
            "move_ee": self._do_move_ee,
            "open_gripper": self._do_open_gripper,
            "close_gripper": self._do_close_gripper,
            "pick": self._do_pick,
            "place": self._do_place,
            "reset": self._do_reset,
            "describe_scene": self._do_describe_scene,
        }.get(tool)

        if handler is None:
            return {"error": f"unknown tool: {tool}"}
        return handler(args)

    # ── tool implementations ─────────────────────────────────────────

    def _do_move_ee(self, args: Dict) -> Dict:
        ok = self._robot.move_ee(
            target_xyz=args["target_xyz"],
            target_rpy=args.get("target_rpy"),
            speed=args.get("speed", 1.0),
        )
        pos, rpy = self._robot.get_ee_pose()
        return {"success": ok, "ee_pos": pos, "ee_rpy": rpy}

    def _do_open_gripper(self, args: Dict) -> Dict:
        self._robot.open_gripper(width=args.get("width", 0.04))
        return {"success": True}

    def _do_close_gripper(self, args: Dict) -> Dict:
        self._robot.close_gripper(force=args.get("force", 40.0))
        return {"success": True}

    def _do_pick(self, args: Dict) -> Dict:
        obj_name = args["object"]
        # Try exact match first, then fuzzy
        if obj_name not in self._scene.objects:
            found = self._scene.find_object_by_substring(obj_name)
            if found:
                obj_name = found
            else:
                return {"success": False, "error": f"object '{args['object']}' not found"}

        ok = self._grasp.pick(obj_name)
        return {"success": ok, "object": obj_name}

    def _do_place(self, args: Dict) -> Dict:
        ok = self._grasp.place(args["target_xyz"])
        return {"success": ok}

    def _do_reset(self, _args: Dict) -> Dict:
        self._robot.reset()
        return {"success": True}

    def _do_describe_scene(self, _args: Dict) -> Any:
        desc = self._scene.describe()
        # Also include EE pose
        pos, rpy = self._robot.get_ee_pose()
        return {
            "objects": desc,
            "ee_position": [round(v, 4) for v in pos],
            "ee_orientation_rpy": [round(v, 4) for v in rpy],
        }
