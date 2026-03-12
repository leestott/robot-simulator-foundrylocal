"""Tests for Scene helper methods that don't require a live PyBullet instance."""

import sys
import types
import unittest

# Mock pybullet before importing scene (heavy native dependency)
_pb_mock = types.ModuleType("pybullet")
for attr in [
    "GEOM_BOX", "GEOM_MESH", "JOINT_FIXED",
    "setAdditionalSearchPath", "loadURDF",
    "createCollisionShape", "createVisualShape", "createMultiBody",
    "getQuaternionFromEuler", "getBasePositionAndOrientation",
    "calculateInverseKinematics", "resetJointState",
]:
    setattr(_pb_mock, attr, None)
sys.modules.setdefault("pybullet", _pb_mock)
sys.modules.setdefault("pybullet_data", types.ModuleType("pybullet_data"))

from src.simulation.scene import Scene, SceneObject


class TestFindObjectBySubstring(unittest.TestCase):
    """Scene.find_object_by_substring – fuzzy name matching."""

    def _scene_with_objects(self, names: list[str]) -> Scene:
        # Bypass __init__ which needs a physics client
        scene = object.__new__(Scene)
        scene.objects = {}
        for i, name in enumerate(names):
            scene.objects[name] = SceneObject(
                body_id=i, name=name, color=(1, 0, 0, 1), spawn_pos=[0, 0, 0]
            )
        return scene

    def test_exact_match(self):
        s = self._scene_with_objects(["cube_1", "sphere_2"])
        self.assertEqual(s.find_object_by_substring("cube_1"), "cube_1")

    def test_substring_match(self):
        s = self._scene_with_objects(["blue_cube_1", "red_sphere_2"])
        self.assertEqual(s.find_object_by_substring("cube"), "blue_cube_1")

    def test_case_insensitive(self):
        s = self._scene_with_objects(["Cube_1"])
        self.assertEqual(s.find_object_by_substring("cube"), "Cube_1")

    def test_no_match(self):
        s = self._scene_with_objects(["cube_1"])
        self.assertIsNone(s.find_object_by_substring("banana"))

    def test_empty_scene(self):
        s = self._scene_with_objects([])
        self.assertIsNone(s.find_object_by_substring("anything"))


class TestMakeName(unittest.TestCase):
    """Scene._make_name generates sequential unique names."""

    def test_sequential(self):
        scene = object.__new__(Scene)
        scene._next_obj_idx = 0
        self.assertEqual(scene._make_name("cube"), "cube_1")
        self.assertEqual(scene._make_name("cube"), "cube_2")
        self.assertEqual(scene._make_name("sphere"), "sphere_3")


class TestGetObjectId(unittest.TestCase):
    def test_existing(self):
        scene = object.__new__(Scene)
        scene.objects = {"c1": SceneObject(body_id=42, name="c1", color=(1,0,0,1), spawn_pos=[0,0,0])}
        self.assertEqual(scene.get_object_id("c1"), 42)

    def test_missing(self):
        scene = object.__new__(Scene)
        scene.objects = {}
        self.assertIsNone(scene.get_object_id("nothing"))


if __name__ == "__main__":
    unittest.main()
