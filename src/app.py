"""Main application – wires simulation, brain, input, and executor together."""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Optional

import pybullet as p

from src.config import Config, parse_args
from src.simulation.scene import Scene
from src.simulation.robot import PandaRobot
from src.simulation.grasp import GraspController
from src.brain.foundry_client import FoundryClient
from src.brain.planner import Planner
from src.executor.action_executor import ActionExecutor
from src.input.text_input import get_text_command
from src.input.voice_input import get_voice_command


def _init_simulation(cfg: Config) -> tuple:
    """Start PyBullet, load scene and robot, return (cid, scene, robot, grasp)."""
    mode = p.GUI if cfg.use_gui else p.DIRECT
    cid = p.connect(mode)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    p.setTimeStep(cfg.time_step, physicsClientId=cid)

    if cfg.use_gui:
        p.resetDebugVisualizerCamera(
            cameraDistance=1.3,
            cameraYaw=50,
            cameraPitch=-25,
            cameraTargetPosition=[0.3, 0, 0.3],
            physicsClientId=cid,
        )

    scene = Scene(cid)
    scene.build_default(cfg.target_object_path)

    robot = PandaRobot(cid)
    grasp = GraspController(robot, scene, cid)

    # Let physics settle
    for _ in range(100):
        p.stepSimulation(physicsClientId=cid)

    return cid, scene, robot, grasp


def _simulation_tick_loop(cid: int, stop_event: threading.Event) -> None:
    """Background thread that keeps the simulation ticking so the GUI stays
    responsive while we wait for user input or LLM responses."""
    while not stop_event.is_set():
        try:
            p.stepSimulation(physicsClientId=cid)
        except Exception:
            break
        time.sleep(1 / 240)


def _command_loop(
    cfg: Config,
    planner: Planner,
    executor: ActionExecutor,
    scene: Scene,
) -> None:
    """Interactive command loop (text or voice)."""
    print("\n" + "=" * 60)
    print("  Robot Simulator – Foundry Local Brain")
    print("  Mode:", cfg.input_mode.upper())
    if cfg.dry_run:
        print("  ⚠  DRY-RUN mode – actions will NOT execute")
    print("=" * 60)
    print("  Try: \"pick up the cube\"")
    print("       \"move to x 0.5 y 0.1 z 0.4\"")
    print("       \"describe the scene\"")
    print("       \"reset\"")
    print("=" * 60)

    while True:
        # --- Get command --------------------------------------------------
        if cfg.input_mode == "voice":
            cmd = get_voice_command(cfg.voice_record_seconds, cfg.whisper_model_alias)
        else:
            cmd = get_text_command()

        if cmd is None:
            print("\nExiting …")
            break

        if not cmd.strip():
            continue

        print(f"\n→ Command: \"{cmd}\"")

        # --- Plan ---------------------------------------------------------
        print("[planner] thinking …")
        actions = planner.plan(cmd)
        if actions is None:
            print("[planner] could not generate a valid action plan.")
            continue

        print(f"[planner] plan ({len(actions)} action(s)):")
        for i, a in enumerate(actions):
            print(f"  {i+1}. {a['tool']}({json.dumps(a['args'])})")

        # --- Execute ------------------------------------------------------
        print("[executor] running plan …")
        results = executor.execute_plan(actions)

        for r in results:
            status = r["status"]
            detail = r.get("result")
            if status == "dry-run":
                print(f"  ✓ {r['tool']} (dry-run)")
            elif isinstance(detail, dict) and detail.get("success") is False:
                print(f"  ✗ {r['tool']}: {detail.get('error', 'failed')}")
            else:
                print(f"  ✓ {r['tool']}")

            # If describe_scene returned data, print it nicely
            if r["tool"] == "describe_scene" and isinstance(detail, dict):
                print("    Scene objects:")
                for obj in detail.get("objects", []):
                    print(f"      {obj['name']}: pos={obj['position']}")
                print(f"    EE pos: {detail.get('ee_position')}")


def main() -> None:
    cfg = parse_args()

    # 1. Initialise simulation
    print("[app] initialising PyBullet simulation …", flush=True)
    cid, scene, robot, grasp = _init_simulation(cfg)

    # 2. Connect to Foundry Local
    print("[app] connecting to Foundry Local …", flush=True)
    client = FoundryClient(cfg)
    if not client.initialise():
        print("[app] FATAL: cannot connect to Foundry Local. Exiting.")
        p.disconnect(cid)
        sys.exit(1)

    models = client.list_models()
    if models:
        print(f"[app] available models: {models}", flush=True)

    # 3. Build planner + executor
    planner = Planner(client, scene)
    executor = ActionExecutor(robot, scene, grasp, dry_run=cfg.dry_run)

    # 4. Start background simulation tick
    stop_event = threading.Event()
    tick_thread = threading.Thread(
        target=_simulation_tick_loop, args=(cid, stop_event), daemon=True
    )
    tick_thread.start()

    # 5a. Web UI mode
    if cfg.web:
        from src.agents.orchestrator import Orchestrator
        from src.web_ui import start_web_server

        orchestrator = Orchestrator(
            config=cfg,
            planner=planner,
            executor=executor,
            client=client,
            scene=scene,
            robot=robot,
        )
        try:
            start_web_server(cfg, orchestrator, cid, foundry_client=client)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            stop_event.set()
            tick_thread.join(timeout=2)
            p.disconnect(cid)
            print("[app] shut down cleanly.")
        return

    # 5b. CLI command loop
    try:
        _command_loop(cfg, planner, executor, scene)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        stop_event.set()
        tick_thread.join(timeout=2)
        p.disconnect(cid)
        print("[app] shut down cleanly.")


if __name__ == "__main__":
    main()
