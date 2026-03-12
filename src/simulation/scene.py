"""Scene setup – ground plane, table, and target objects."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pybullet as p
import pybullet_data


@dataclass
class SceneObject:
    """Metadata for a spawned object."""

    body_id: int
    name: str
    color: Tuple[float, float, float, float]
    spawn_pos: List[float]


class Scene:
    """Manages the PyBullet world: ground, table, and target objects."""

    def __init__(self, physics_client: int) -> None:
        self._cid = physics_client
        self.objects: Dict[str, SceneObject] = {}
        self._next_obj_idx = 0

    # ── public API ───────────────────────────────────────────────────

    def build_default(self, target_object_path: Optional[str] = None) -> None:
        """Create the ground, table, and one target object."""
        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self._cid)

        # Ground plane
        p.loadURDF("plane.urdf", physicsClientId=self._cid)

        # Table – scaled down so the robot stands beside it
        table_id = p.loadURDF(
            "table/table.urdf",
            basePosition=[0.5, 0.0, 0.0],
            baseOrientation=p.getQuaternionFromEuler([0, 0, 0]),
            useFixedBase=True,
            globalScaling=0.5,
            physicsClientId=self._cid,
        )

        if target_object_path:
            self._load_custom_object(target_object_path)
        else:
            self._spawn_default_cube()

    def _spawn_default_cube(self) -> None:
        """Spawn a small coloured cube on the table."""
        half = 0.025
        col_id = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=[half, half, half], physicsClientId=self._cid
        )
        vis_id = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=[half, half, half],
            rgbaColor=[0.2, 0.6, 1.0, 1.0],
            physicsClientId=self._cid,
        )
        pos = [0.5, 0.0, 0.34]
        body = p.createMultiBody(
            baseMass=0.1,
            baseCollisionShapeIndex=col_id,
            baseVisualShapeIndex=vis_id,
            basePosition=pos,
            physicsClientId=self._cid,
        )
        name = self._make_name("cube")
        self.objects[name] = SceneObject(
            body_id=body, name=name, color=(0.2, 0.6, 1.0, 1.0), spawn_pos=pos
        )

    def _load_custom_object(self, path: str) -> None:
        """Load a mesh (OBJ/STL) or URDF from *path*."""
        ext = os.path.splitext(path)[1].lower()
        pos = [0.5, 0.0, 0.34]

        if ext == ".urdf":
            body = p.loadURDF(path, basePosition=pos, physicsClientId=self._cid)
        elif ext in (".obj", ".stl"):
            col_id = p.createCollisionShape(
                p.GEOM_MESH, fileName=path, meshScale=[0.05, 0.05, 0.05],
                physicsClientId=self._cid,
            )
            vis_id = p.createVisualShape(
                p.GEOM_MESH, fileName=path, meshScale=[0.05, 0.05, 0.05],
                rgbaColor=[0.9, 0.3, 0.2, 1.0],
                physicsClientId=self._cid,
            )
            body = p.createMultiBody(
                baseMass=0.1,
                baseCollisionShapeIndex=col_id,
                baseVisualShapeIndex=vis_id,
                basePosition=pos,
                physicsClientId=self._cid,
            )
        else:
            print(f"[scene] unsupported object format '{ext}', spawning default cube")
            self._spawn_default_cube()
            return

        name = self._make_name("object")
        self.objects[name] = SceneObject(
            body_id=body, name=name, color=(0.9, 0.3, 0.2, 1.0), spawn_pos=pos
        )

    # ── scene queries ────────────────────────────────────────────────

    def describe(self) -> List[Dict]:
        """Return a list of dicts describing every spawned object."""
        descriptions: List[Dict] = []
        for name, obj in self.objects.items():
            pos, orn = p.getBasePositionAndOrientation(
                obj.body_id, physicsClientId=self._cid
            )
            descriptions.append(
                {
                    "name": name,
                    "position": [round(v, 4) for v in pos],
                    "orientation_quat": [round(v, 4) for v in orn],
                    "color_rgba": list(obj.color),
                }
            )
        return descriptions

    def get_object_position(self, name: str) -> Optional[List[float]]:
        """Return the current [x, y, z] of *name*, or None."""
        obj = self.objects.get(name)
        if obj is None:
            return None
        pos, _ = p.getBasePositionAndOrientation(
            obj.body_id, physicsClientId=self._cid
        )
        return list(pos)

    def get_object_id(self, name: str) -> Optional[int]:
        obj = self.objects.get(name)
        return obj.body_id if obj else None

    def find_object_by_substring(self, query: str) -> Optional[str]:
        """Fuzzy match: return the first object whose name contains *query*."""
        q = query.lower()
        for name in self.objects:
            if q in name.lower():
                return name
        return None

    # ── helpers ──────────────────────────────────────────────────────

    def _make_name(self, prefix: str) -> str:
        self._next_obj_idx += 1
        return f"{prefix}_{self._next_obj_idx}"
