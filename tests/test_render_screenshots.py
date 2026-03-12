"""Standalone test script – starts the PyBullet simulation, renders screenshots
via offscreen rendering, and saves them to docs/screenshots/."""

from __future__ import annotations

import os
import sys
import math

# Ensure src is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pybullet as p
import pybullet_data
import numpy as np
from PIL import Image

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")
WIDTH, HEIGHT = 1920, 1080


def save_pybullet_image(cid: int, filename: str, cam_distance: float = 1.5,
                         cam_yaw: float = 45, cam_pitch: float = -30,
                         cam_target: list = None) -> str:
    """Render a frame from PyBullet and save as PNG."""
    if cam_target is None:
        cam_target = [0.5, 0.0, 0.4]

    view_matrix = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=cam_target,
        distance=cam_distance,
        yaw=cam_yaw,
        pitch=cam_pitch,
        roll=0,
        upAxisIndex=2,
    )
    proj_matrix = p.computeProjectionMatrixFOV(
        fov=60, aspect=WIDTH / HEIGHT, nearVal=0.1, farVal=100
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width=WIDTH, height=HEIGHT,
        viewMatrix=view_matrix,
        projectionMatrix=proj_matrix,
        renderer=p.ER_TINY_RENDERER,
        physicsClientId=cid,
    )
    img = np.array(rgba, dtype=np.uint8).reshape(HEIGHT, WIDTH, 4)
    path = os.path.join(SCREENSHOTS_DIR, filename)
    Image.fromarray(img[:, :, :3]).save(path)
    print(f"  saved: {path}")
    return path


def _set_pose(robot_id, joint_values, cid):
    """Teleport robot joints to the given values."""
    for i, q in enumerate(joint_values):
        p.resetJointState(robot_id, i, q, physicsClientId=cid)


def _set_gripper(robot_id, width, cid):
    """Set gripper finger width."""
    p.resetJointState(robot_id, 9, width, physicsClientId=cid)
    p.resetJointState(robot_id, 10, width, physicsClientId=cid)


def main():
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    # Start headless PyBullet
    cid = p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)

    # Load scene – table lowered so robot reaches over/down to it
    p.loadURDF("plane.urdf", physicsClientId=cid)
    p.loadURDF(
        "table/table.urdf",
        basePosition=[0.5, 0.0, 0.0],
        useFixedBase=True,
        globalScaling=0.5,
        physicsClientId=cid,
    )

    # Spawn a cube on the scaled table surface (~z=0.3125)
    cube_pos = [0.5, 0.0, 0.34]
    half = 0.025
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[half]*3, physicsClientId=cid)
    vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[half]*3,
                               rgbaColor=[0.2, 0.6, 1.0, 1.0], physicsClientId=cid)
    cube_id = p.createMultiBody(baseMass=0.1, baseCollisionShapeIndex=col,
                      baseVisualShapeIndex=vis, basePosition=cube_pos,
                      physicsClientId=cid)

    # Load robot
    robot_id = p.loadURDF(
        "franka_panda/panda.urdf",
        basePosition=[0, 0, 0],
        useFixedBase=True,
        physicsClientId=cid,
    )

    # --- Poses ----------------------------------------------------------------
    neutral = [0, -0.785, 0, -2.356, 0, 1.571, 0.785]
    # Arm extended forward toward the cube on the smaller table
    reaching = [0.0, 0.3, 0.0, -1.2, 0.0, 1.85, 0.785]
    # Arm hovering above cube, gripper open
    above_cube = [0.0, 0.5, 0.0, -0.9, 0.0, 1.75, 0.785]

    # --- Screenshots ----------------------------------------------------------
    print("Capturing screenshots …")

    # 1. Overview – neutral pose, camera framing both robot and table
    _set_pose(robot_id, neutral, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    save_pybullet_image(cid, "01_overview.png",
                        cam_distance=1.3, cam_yaw=50, cam_pitch=-25,
                        cam_target=[0.3, 0.0, 0.25])

    # 2. Robot reaching toward cube – 3/4 angle
    _set_pose(robot_id, reaching, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    save_pybullet_image(cid, "02_reaching.png",
                        cam_distance=1.0, cam_yaw=40, cam_pitch=-20,
                        cam_target=[0.3, 0.0, 0.3])

    # 3. Arm above cube, gripper open – ready to grasp
    _set_pose(robot_id, above_cube, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    save_pybullet_image(cid, "03_above_cube.png",
                        cam_distance=0.7, cam_yaw=35, cam_pitch=-30,
                        cam_target=[0.35, 0.0, 0.3])

    # 4. Close-up of gripper near cube – interaction detail
    save_pybullet_image(cid, "04_gripper_detail.png",
                        cam_distance=0.35, cam_yaw=25, cam_pitch=-15,
                        cam_target=[0.4, 0.0, 0.34])

    # 5. Front view showing arm extent to table
    _set_pose(robot_id, reaching, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(50):
        p.stepSimulation(physicsClientId=cid)
    save_pybullet_image(cid, "05_front_interaction.png",
                        cam_distance=1.1, cam_yaw=0, cam_pitch=-20,
                        cam_target=[0.3, 0.0, 0.25])

    # 6. Side view showing robot-table-cube spatial relationship
    save_pybullet_image(cid, "06_side_layout.png",
                        cam_distance=1.3, cam_yaw=90, cam_pitch=-15,
                        cam_target=[0.3, 0.0, 0.2])

    p.disconnect(cid)
    print(f"\nDone! {len(os.listdir(SCREENSHOTS_DIR))} screenshots saved to {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
