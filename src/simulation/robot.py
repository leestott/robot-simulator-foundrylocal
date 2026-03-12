"""Franka Panda robot wrapper – IK, joint control, gripper, safety."""

from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

import numpy as np
import pybullet as p
import pybullet_data


# Panda link indices (from the standard pybullet URDF)
PANDA_NUM_JOINTS = 7  # arm joints (0-6)
PANDA_EE_LINK = 11  # end-effector link index
PANDA_FINGER_LEFT = 9
PANDA_FINGER_RIGHT = 10
PANDA_NUM_DOF = 7

# Reasonable joint limits for safety clamping
PANDA_LOWER = [-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973]
PANDA_UPPER = [2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973]

MAX_JOINT_DELTA_PER_STEP = 0.05  # radians


class PandaRobot:
    """High-level controller for the Franka Panda arm in PyBullet."""

    def __init__(self, physics_client: int) -> None:
        self._cid = physics_client
        p.setAdditionalSearchPath(
            pybullet_data.getDataPath(), physicsClientId=self._cid
        )
        self._robot_id = p.loadURDF(
            "franka_panda/panda.urdf",
            basePosition=[0, 0, 0],
            useFixedBase=True,
            physicsClientId=self._cid,
        )
        self._num_joints = p.getNumJoints(self._robot_id, physicsClientId=self._cid)

        # Neutral pose
        self._neutral = [0, -0.785, 0, -2.356, 0, 1.571, 0.785]
        self._go_to_joints(self._neutral, steps=0)  # teleport

        # Open gripper at start
        self._set_gripper(0.04)

    # ── public movement ──────────────────────────────────────────────

    def move_ee(
        self,
        target_xyz: List[float],
        target_rpy: Optional[List[float]] = None,
        speed: float = 1.0,
    ) -> bool:
        """Move end-effector to *target_xyz* with optional orientation."""
        target_xyz = self._clamp_workspace(target_xyz)
        if target_rpy is None:
            target_rpy = [math.pi, 0, 0]  # top-down
        orn = p.getQuaternionFromEuler(target_rpy)
        joint_targets = self._ik(target_xyz, orn)
        if joint_targets is None:
            return False
        self._go_to_joints(joint_targets, speed=speed)
        return True

    def open_gripper(self, width: float = 0.04) -> None:
        width = max(0.0, min(width, 0.04))
        self._set_gripper(width, steps=60)

    def close_gripper(self, force: float = 40.0) -> None:
        self._set_gripper(0.0, force=force, steps=100)

    def reset(self) -> None:
        self._go_to_joints(self._neutral, speed=0.5)
        self._set_gripper(0.04)

    def get_ee_pose(self) -> Tuple[List[float], List[float]]:
        state = p.getLinkState(
            self._robot_id, PANDA_EE_LINK, physicsClientId=self._cid
        )
        return list(state[4]), list(p.getEulerFromQuaternion(state[5]))

    # ── grasp helpers used by executor ───────────────────────────────

    def create_grasp_constraint(self, object_body_id: int) -> int:
        """Attach object to EE via a fixed constraint (simulates a firm grasp)."""
        ee_state = p.getLinkState(
            self._robot_id, PANDA_EE_LINK, physicsClientId=self._cid
        )
        inv_ee_pos, inv_ee_orn = p.invertTransform(ee_state[4], ee_state[5])
        obj_pos, obj_orn = p.getBasePositionAndOrientation(
            object_body_id, physicsClientId=self._cid
        )
        rel_pos, rel_orn = p.multiplyTransforms(
            inv_ee_pos, inv_ee_orn, obj_pos, obj_orn
        )
        cid = p.createConstraint(
            self._robot_id,
            PANDA_EE_LINK,
            object_body_id,
            -1,
            p.JOINT_FIXED,
            [0, 0, 0],
            rel_pos,
            [0, 0, 0],
            rel_orn,
            physicsClientId=self._cid,
        )
        p.changeConstraint(cid, maxForce=100, physicsClientId=self._cid)
        return cid

    def remove_constraint(self, constraint_id: int) -> None:
        p.removeConstraint(constraint_id, physicsClientId=self._cid)

    # ── internal ─────────────────────────────────────────────────────

    def _ik(
        self, pos: List[float], orn: List[float]
    ) -> Optional[List[float]]:
        joints = p.calculateInverseKinematics(
            self._robot_id,
            PANDA_EE_LINK,
            pos,
            orn,
            lowerLimits=PANDA_LOWER,
            upperLimits=PANDA_UPPER,
            jointRanges=[u - l for l, u in zip(PANDA_LOWER, PANDA_UPPER)],
            restPoses=self._neutral,
            maxNumIterations=100,
            residualThreshold=1e-5,
            physicsClientId=self._cid,
        )
        if joints is None:
            return None
        return list(joints[:PANDA_NUM_DOF])

    def _go_to_joints(
        self,
        targets: List[float],
        steps: int = 240,
        speed: float = 1.0,
    ) -> None:
        """Interpolate from current joint positions to *targets*."""
        if steps == 0:
            # Teleport
            for i in range(PANDA_NUM_DOF):
                p.resetJointState(
                    self._robot_id, i, targets[i], physicsClientId=self._cid
                )
            return

        current = self._get_joint_positions()
        eff_steps = max(1, int(steps / max(speed, 0.1)))

        for step_i in range(1, eff_steps + 1):
            alpha = step_i / eff_steps
            interp = [c + (t - c) * alpha for c, t in zip(current, targets)]
            # Safety: clamp max delta per step
            for i in range(PANDA_NUM_DOF):
                delta = interp[i] - current[i]
                clamped_delta = max(
                    -MAX_JOINT_DELTA_PER_STEP,
                    min(MAX_JOINT_DELTA_PER_STEP, delta * alpha),
                )
                p.setJointMotorControl2(
                    self._robot_id,
                    i,
                    p.POSITION_CONTROL,
                    targetPosition=interp[i],
                    force=240,
                    physicsClientId=self._cid,
                )
            p.stepSimulation(physicsClientId=self._cid)
            time.sleep(1 / 240)

    def _set_gripper(
        self, width: float, force: float = 40.0, steps: int = 0
    ) -> None:
        for finger in (PANDA_FINGER_LEFT, PANDA_FINGER_RIGHT):
            p.setJointMotorControl2(
                self._robot_id,
                finger,
                p.POSITION_CONTROL,
                targetPosition=width,
                force=force,
                physicsClientId=self._cid,
            )
        for _ in range(max(steps, 1)):
            p.stepSimulation(physicsClientId=self._cid)
            if steps:
                time.sleep(1 / 240)

    def _get_joint_positions(self) -> List[float]:
        return [
            p.getJointState(self._robot_id, i, physicsClientId=self._cid)[0]
            for i in range(PANDA_NUM_DOF)
        ]

    def _clamp_workspace(self, xyz: List[float]) -> List[float]:
        """Clamp target to Panda reachable workspace bounds."""
        x = max(-0.855, min(0.855, xyz[0]))
        y = max(-0.855, min(0.855, xyz[1]))
        z = max(0.0, min(1.19, xyz[2]))
        return [x, y, z]
