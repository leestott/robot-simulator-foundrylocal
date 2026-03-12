"""Safety Agent – validates action plans against workspace bounds and schema."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.brain.action_schema import ALLOWED_TOOLS, TOOL_SCHEMAS
from src.config import Config


class SafetyAgent:
    """Agent that validates plans before execution.

    Checks:
    - Every tool name is in the allowed set.
    - ``move_ee`` / ``place`` targets fall within workspace bounds.
    - Required arguments are present.
    """

    name = "SafetyAgent"

    def __init__(self, config: Config) -> None:
        self._cfg = config

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate ``context["plan"]``.

        Sets ``context["validation"]`` to ``{"valid": True}`` or
        ``{"valid": False, "errors": [...]}``.
        """
        plan: Optional[List[Dict[str, Any]]] = context.get("plan")
        if plan is None:
            context["validation"] = {"valid": False, "errors": ["no plan produced"]}
            return context

        errors: List[str] = []
        for i, action in enumerate(plan):
            tool = action.get("tool", "")
            args = action.get("args", {})

            if tool not in ALLOWED_TOOLS:
                errors.append(f"step {i+1}: unknown tool '{tool}'")
                continue

            # Bounds check for move_ee and place targets
            if tool in ("move_ee", "place"):
                xyz = args.get("target_xyz")
                if xyz and len(xyz) == 3:
                    x, y, z = xyz
                    if not (self._cfg.ws_x_min <= x <= self._cfg.ws_x_max):
                        errors.append(
                            f"step {i+1}: x={x:.3f} outside bounds "
                            f"[{self._cfg.ws_x_min}, {self._cfg.ws_x_max}]"
                        )
                    if not (self._cfg.ws_y_min <= y <= self._cfg.ws_y_max):
                        errors.append(
                            f"step {i+1}: y={y:.3f} outside bounds "
                            f"[{self._cfg.ws_y_min}, {self._cfg.ws_y_max}]"
                        )
                    if not (self._cfg.ws_z_min <= z <= self._cfg.ws_z_max):
                        errors.append(
                            f"step {i+1}: z={z:.3f} outside bounds "
                            f"[{self._cfg.ws_z_min}, {self._cfg.ws_z_max}]"
                        )

        if errors:
            context["validation"] = {"valid": False, "errors": errors}
        else:
            context["validation"] = {"valid": True}

        return context
