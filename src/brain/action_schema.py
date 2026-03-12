"""Strict JSON action schema – defines the contract between the LLM and the executor."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

# ── Allowed tool definitions ─────────────────────────────────────────

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "move_ee": {
        "description": "Move the end-effector to an XYZ position with optional RPY orientation and speed.",
        "args": {
            "target_xyz": {"type": "list[float]", "length": 3, "required": True},
            "target_rpy": {"type": "list[float]", "length": 3, "required": False},
            "speed": {"type": "float", "required": False, "default": 1.0},
        },
    },
    "open_gripper": {
        "description": "Open the gripper to a specified width (metres, max 0.04).",
        "args": {
            "width": {"type": "float", "required": False, "default": 0.04},
        },
    },
    "close_gripper": {
        "description": "Close the gripper with a given force (newtons).",
        "args": {
            "force": {"type": "float", "required": False, "default": 40.0},
        },
    },
    "pick": {
        "description": "Pick up an object by name. Executes the full approach-descend-close-lift sequence.",
        "args": {
            "object": {"type": "str", "required": True},
        },
    },
    "place": {
        "description": "Place the currently held object at the given XYZ position.",
        "args": {
            "target_xyz": {"type": "list[float]", "length": 3, "required": True},
        },
    },
    "reset": {
        "description": "Return the robot to its neutral position and open gripper.",
        "args": {},
    },
    "describe_scene": {
        "description": "Return a list of all objects in the scene with their positions and colours.",
        "args": {},
    },
}

ALLOWED_TOOLS = set(TOOL_SCHEMAS.keys())


def schema_prompt_block() -> str:
    """Return a human-readable description of the schema for the system prompt."""
    lines = ["Available tools (use ONLY these):"]
    for name, info in TOOL_SCHEMAS.items():
        args_desc = ", ".join(
            f"{k}: {v['type']}" + (" (required)" if v.get("required") else " (optional)")
            for k, v in info["args"].items()
        )
        lines.append(f'  - {name}({args_desc}): {info["description"]}')
    return "\n".join(lines)


# ── Validation ───────────────────────────────────────────────────────


def validate_plan(raw: Any) -> Optional[List[Dict[str, Any]]]:
    """Parse and validate a plan/action payload.

    Accepted shapes:
        {"type": "plan", "actions": [...]}
        {"type": "action", "tool": "...", "args": {...}}
        {"tool": "...", "args": {...}}            # shorthand single action

    Returns a list of validated action dicts, or None on failure.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None

    if not isinstance(raw, dict):
        return None

    payload_type = raw.get("type", "action")

    if payload_type == "plan":
        actions = raw.get("actions")
        if not isinstance(actions, list):
            return None
    else:
        actions = [raw]

    validated: List[Dict[str, Any]] = []
    for act in actions:
        v = _validate_single(act)
        if v is None:
            return None  # reject entire plan if one action is invalid
        validated.append(v)

    return validated


def _validate_single(act: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tool = act.get("tool")
    # Handle LLM pattern: {"type": "<tool_name>", "args": {...}} with no "tool"
    if tool is None:
        t = act.get("type", "")
        if t in ALLOWED_TOOLS:
            tool = t
    if tool not in ALLOWED_TOOLS:
        return None
    schema_args = TOOL_SCHEMAS[tool]["args"]
    provided = act.get("args", {})
    if not isinstance(provided, dict):
        return None

    clean_args: Dict[str, Any] = {}
    for arg_name, arg_def in schema_args.items():
        if arg_name in provided:
            val = provided[arg_name]
            # Basic type coercion / checking
            if "list" in arg_def["type"] and isinstance(val, list):
                expected_len = arg_def.get("length")
                if expected_len and len(val) != expected_len:
                    return None
                clean_args[arg_name] = [float(v) for v in val]
            elif arg_def["type"] == "float":
                clean_args[arg_name] = float(val)
            elif arg_def["type"] == "str":
                clean_args[arg_name] = str(val)
            else:
                clean_args[arg_name] = val
        elif arg_def.get("required"):
            return None  # missing required arg
        else:
            clean_args[arg_name] = arg_def.get("default")

    return {"tool": tool, "args": clean_args}
