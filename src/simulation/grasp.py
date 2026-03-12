"""Pick-and-place grasp routines with success validation."""

from __future__ import annotations

import time
from typing import List, Optional

import pybullet as p

from src.simulation.robot import PandaRobot
from src.simulation.scene import Scene


# Heights (metres, world frame)
APPROACH_HEIGHT = 0.20  # above grasp point
GRASP_HEIGHT_OFFSET = 0.04  # lower to the object top
LIFT_HEIGHT = 0.25


class GraspController:
    """Orchestrates pick / place sequences."""

    def __init__(
        self, robot: PandaRobot, scene: Scene, physics_client: int
    ) -> None:
        self._robot = robot
        self._scene = scene
        self._cid = physics_client
        self._active_constraint: Optional[int] = None
        self._grasped_object: Optional[str] = None

    # ── pick ─────────────────────────────────────────────────────────

    def pick(self, object_name: str) -> bool:
        """Execute approach → descend → close → lift and validate."""
        pos = self._scene.get_object_position(object_name)
        if pos is None:
            print(f"[grasp] object '{object_name}' not found in scene")
            return False

        obj_id = self._scene.get_object_id(object_name)
        if obj_id is None:
            return False

        # 1. Open gripper
        self._robot.open_gripper(0.04)
        self._step(30)

        # 2. Move above object
        approach = [pos[0], pos[1], pos[2] + APPROACH_HEIGHT]
        if not self._robot.move_ee(approach):
            print("[grasp] IK failed for approach")
            return False
        self._step(30)

        # 3. Descend to grasp height
        grasp_pos = [pos[0], pos[1], pos[2] + GRASP_HEIGHT_OFFSET]
        if not self._robot.move_ee(grasp_pos):
            print("[grasp] IK failed for descend")
            return False
        self._step(30)

        # 4. Close gripper
        self._robot.close_gripper(force=50.0)
        self._step(60)

        # 5. Attach via constraint
        self._active_constraint = self._robot.create_grasp_constraint(obj_id)
        self._grasped_object = object_name
        self._step(10)

        # 6. Lift
        lift_pos = [pos[0], pos[1], pos[2] + LIFT_HEIGHT]
        self._robot.move_ee(lift_pos)
        self._step(60)

        # 7. Validate
        success = self._validate_grasp(object_name)
        if success:
            print(f"[grasp] successfully picked '{object_name}'")
        else:
            print(f"[grasp] pick FAILED for '{object_name}'")
            self._release()
        return success

    # ── place ────────────────────────────────────────────────────────

    def place(self, target_xyz: List[float]) -> bool:
        """Place the currently held object at *target_xyz*."""
        if self._active_constraint is None:
            print("[grasp] nothing grasped – cannot place")
            return False

        # Move above target
        above = [target_xyz[0], target_xyz[1], target_xyz[2] + APPROACH_HEIGHT]
        self._robot.move_ee(above)
        self._step(30)

        # Lower
        self._robot.move_ee(target_xyz)
        self._step(30)

        # Release
        self._release()
        self._robot.open_gripper(0.04)
        self._step(30)

        # Retreat up
        self._robot.move_ee(above)
        self._step(30)
        print(f"[grasp] placed object at {target_xyz}")
        return True

    # ── internal ─────────────────────────────────────────────────────

    def _release(self) -> None:
        if self._active_constraint is not None:
            self._robot.remove_constraint(self._active_constraint)
            self._active_constraint = None
            self._grasped_object = None

    def _validate_grasp(self, object_name: str) -> bool:
        """Check that the object is higher than its spawn position."""
        pos = self._scene.get_object_position(object_name)
        if pos is None:
            return False
        obj = self._scene.objects.get(object_name)
        if obj is None:
            return False
        return pos[2] > obj.spawn_pos[2] + 0.03

    def _step(self, n: int = 1) -> None:
        for _ in range(n):
            p.stepSimulation(physicsClientId=self._cid)
            time.sleep(1 / 240)
