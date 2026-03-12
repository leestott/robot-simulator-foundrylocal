"""Render app-in-action screenshots that show the simulation with command overlays.

Creates composited images: PyBullet render + semi-transparent command bar,
simulating what the user would see during an interactive session.
"""

from __future__ import annotations

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pybullet as p
import pybullet_data
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCREENSHOTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "screenshots",
)
WIDTH, HEIGHT = 1920, 1080


def render_frame(cid, cam_distance=1.3, cam_yaw=50, cam_pitch=-25,
                 cam_target=None):
    if cam_target is None:
        cam_target = [0.3, 0.0, 0.25]
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=cam_target,
        distance=cam_distance, yaw=cam_yaw, pitch=cam_pitch,
        roll=0, upAxisIndex=2,
    )
    proj = p.computeProjectionMatrixFOV(
        fov=60, aspect=WIDTH / HEIGHT, nearVal=0.1, farVal=100,
    )
    _, _, rgba, _, _ = p.getCameraImage(
        WIDTH, HEIGHT, view, proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=cid,
    )
    return np.array(rgba, dtype=np.uint8).reshape(HEIGHT, WIDTH, 4)[:, :, :3]


def add_command_overlay(img_array, command_text, response_text=""):
    """Add a semi-transparent command bar at the bottom of the image."""
    img = Image.fromarray(img_array)
    draw = ImageDraw.Draw(img, "RGBA")

    bar_height = 120
    y_start = HEIGHT - bar_height

    # Semi-transparent dark bar
    draw.rectangle(
        [(0, y_start), (WIDTH, HEIGHT)],
        fill=(20, 20, 30, 200),
    )

    # Try to use a monospace font; fall back to default
    try:
        font = ImageFont.truetype("consola.ttf", 22)
        font_small = ImageFont.truetype("consola.ttf", 18)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("cour.ttf", 22)
            font_small = ImageFont.truetype("cour.ttf", 18)
        except (OSError, IOError):
            font = ImageFont.load_default()
            font_small = font

    # Command prompt
    prompt = f"🤖 Enter command (or 'quit'): {command_text}"
    draw.text((30, y_start + 15), prompt, fill=(0, 255, 120), font=font)

    # Response
    if response_text:
        draw.text((30, y_start + 50), response_text, fill=(180, 200, 255), font=font_small)

    # Title bar at top
    draw.rectangle([(0, 0), (WIDTH, 45)], fill=(20, 20, 30, 180))
    draw.text(
        (30, 10),
        "Robot Arm Simulator – Foundry Local Brain  |  Mode: TEXT  |  Model: phi-4-mini",
        fill=(200, 220, 255),
        font=font_small,
    )

    return np.array(img)


def _set_pose(robot_id, joint_values, cid):
    for i, q in enumerate(joint_values):
        p.resetJointState(robot_id, i, q, physicsClientId=cid)


def _set_gripper(robot_id, width, cid):
    p.resetJointState(robot_id, 9, width, physicsClientId=cid)
    p.resetJointState(robot_id, 10, width, physicsClientId=cid)


def main():
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    cid = p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)

    # Scene
    p.loadURDF("plane.urdf", physicsClientId=cid)
    p.loadURDF(
        "table/table.urdf",
        basePosition=[0.5, 0.0, 0.0],
        useFixedBase=True,
        globalScaling=0.5,
        physicsClientId=cid,
    )

    cube_pos = [0.5, 0.0, 0.34]
    half = 0.025
    col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[half] * 3, physicsClientId=cid)
    vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[half] * 3,
                               rgbaColor=[0.2, 0.6, 1.0, 1.0], physicsClientId=cid)
    cube_id = p.createMultiBody(baseMass=0.1, baseCollisionShapeIndex=col,
                                 baseVisualShapeIndex=vis, basePosition=cube_pos,
                                 physicsClientId=cid)

    robot_id = p.loadURDF(
        "franka_panda/panda.urdf",
        basePosition=[0, 0, 0],
        useFixedBase=True,
        physicsClientId=cid,
    )

    neutral = [0, -0.785, 0, -2.356, 0, 1.571, 0.785]
    reaching = [0.0, 0.3, 0.0, -1.2, 0.0, 1.85, 0.785]
    above_cube = [0.0, 0.5, 0.0, -0.9, 0.0, 1.75, 0.785]

    print("Rendering app screenshots …")

    # 1. describe the scene
    _set_pose(robot_id, neutral, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    frame = render_frame(cid, cam_distance=1.3, cam_yaw=50, cam_pitch=-25,
                         cam_target=[0.3, 0.0, 0.25])
    frame = add_command_overlay(
        frame,
        "describe the scene",
        "→ [planner] plan (1 action): describe_scene({})    ✓ cube_1: pos=[0.5, 0.0, 0.34]",
    )
    Image.fromarray(frame).save(os.path.join(SCREENSHOTS_DIR, "app_describe.png"))
    print("  saved: app_describe.png")

    # 2. pick up the cube
    _set_pose(robot_id, reaching, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    frame = render_frame(cid, cam_distance=1.0, cam_yaw=40, cam_pitch=-20,
                         cam_target=[0.3, 0.0, 0.3])
    frame = add_command_overlay(
        frame,
        "pick up the cube",
        "→ [planner] plan (1 action): pick({\"object\": \"cube_1\"})    ✓ pick executed",
    )
    Image.fromarray(frame).save(os.path.join(SCREENSHOTS_DIR, "app_pick.png"))
    print("  saved: app_pick.png")

    # 3. move to position
    _set_pose(robot_id, above_cube, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    frame = render_frame(cid, cam_distance=0.9, cam_yaw=35, cam_pitch=-25,
                         cam_target=[0.35, 0.0, 0.3])
    frame = add_command_overlay(
        frame,
        "move to x 0.4 y 0.1 z 0.3",
        "→ [planner] plan (1 action): move_ee({\"target_xyz\": [0.4, 0.1, 0.3]})    ✓ move_ee done",
    )
    Image.fromarray(frame).save(os.path.join(SCREENSHOTS_DIR, "app_move.png"))
    print("  saved: app_move.png")

    # 4. reset
    _set_pose(robot_id, neutral, cid)
    _set_gripper(robot_id, 0.04, cid)
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)
    frame = render_frame(cid, cam_distance=1.3, cam_yaw=50, cam_pitch=-25,
                         cam_target=[0.3, 0.0, 0.25])
    frame = add_command_overlay(
        frame,
        "reset",
        "→ [planner] plan (1 action): reset({})    ✓ reset executed — robot in neutral pose",
    )
    Image.fromarray(frame).save(os.path.join(SCREENSHOTS_DIR, "app_reset.png"))
    print("  saved: app_reset.png")

    p.disconnect(cid)
    print(f"\nDone! App screenshots saved to {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
