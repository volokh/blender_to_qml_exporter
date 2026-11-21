"""Run with python3 tests/test_lod_winding.py."""
import sys
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qt_simplifier


def grid_data(subdivisions=8):
    points = np.array([(x, y, 0.0) for y in range(subdivisions + 1)
                       for x in range(subdivisions + 1)], dtype=np.float32)
    normals = np.tile(np.array((0.0, 0.0, 1.0), dtype=np.float32), (len(points), 1))
    indices = []
    for y in range(subdivisions):
        for x in range(subdivisions):
            first = y * (subdivisions + 1) + x
            indices.extend((first, first + 1, first + subdivisions + 2,
                            first, first + subdivisions + 2, first + subdivisions + 1))
    return points, normals, indices


def assert_ccw_reduced(test_case, points, base_indices, levels):
    base_normal = np.cross(points[base_indices[1]] - points[base_indices[0]],
                           points[base_indices[2]] - points[base_indices[0]])
    for level, subsets in levels.items():
        reduced_indices, _distance = subsets[0]
        test_case.assertLess(len(reduced_indices), len(base_indices), f"LOD{level} was not reduced")
        for offset in range(0, len(reduced_indices), 3):
            a, b, c = reduced_indices[offset:offset + 3]
            normal = np.cross(points[b] - points[a], points[c] - points[a])
            test_case.assertGreater(float(np.dot(normal, base_normal)), 0.0,
                                    f"LOD{level} triangle at {offset // 3} changed winding")


def reverse_simplify(destination, indices, _positions, target_index_count=None, **_options):
    count = max(3, (int(target_index_count) // 3) * 3)
    triangles = np.array(indices[:count], dtype=np.uint32).reshape(-1, 3).copy()
    triangles[:, [1, 2]] = triangles[:, [2, 1]]
    destination[:count] = triangles.reshape(-1)
    return count


class LodWindingTests(unittest.TestCase):
    def test_qt_compatible_reduction_keeps_source_winding(self):
        points, normals, indices = grid_data()
        levels, _new_vertices = qt_simplifier.build_generated_lods(
            points, normals, [(0, len(indices))], indices, highest=3, vertex_base=len(points))

        self.assertTrue(levels)
        assert_ccw_reduced(self, points, indices, levels)

    def test_vertex_capped_reduction_keeps_source_winding(self):
        points, normals, indices = grid_data()
        def reverse_simplification(source_indices, _positions, target_index_count):
            first_triangle = source_indices[:3]
            reversed_triangle = [first_triangle[0], first_triangle[2], first_triangle[1]]
            count = min(target_index_count, len(source_indices) // 2)
            count -= count % 3
            return reversed_triangle * (count // 3), 0.1

        with patch.object(qt_simplifier, "simplify_edge", side_effect=reverse_simplification):
            levels, _new_vertices = qt_simplifier.build_generated_lods(
                points, normals, [(0, len(indices))], indices, highest=2, vertex_base=len(points),
                angles=(60.0, 0.0), capped=True)

        self.assertTrue(levels)
        assert_ccw_reduced(self, points, indices, levels)
        for level, subsets in levels.items():
            self.assertLessEqual(len(set(subsets[0][0])), len(points) >> level)

    def test_meshoptimizer_reversed_output_is_corrected(self):
        points, normals, indices = grid_data()
        fake_module = ModuleType("meshoptimizer")
        fake_module.simplify = reverse_simplify
        with patch.dict(sys.modules, {"meshoptimizer": fake_module}):
            levels, _new_vertices = qt_simplifier.build_meshoptimizer_lods(
                points, normals, [(0, len(indices))], indices, highest=3, vertex_base=len(points))

        self.assertTrue(levels)
        assert_ccw_reduced(self, points, indices, levels)

    def test_meshoptimizer_receives_per_lod_index_targets(self):
        points, normals, indices = grid_data(16)
        calls = []
        fake_module = ModuleType("meshoptimizer")

        def record_simplify(destination, source_indices, vertex_positions, target_index_count=None, **_options):
            self.assertIsInstance(destination, np.ndarray)
            self.assertEqual(destination.dtype, np.uint32)
            self.assertEqual(source_indices.dtype, np.uint32)
            self.assertEqual(vertex_positions.dtype, np.float32)
            calls.append(target_index_count)
            count = int(target_index_count) - int(target_index_count) % 3
            destination[:count] = source_indices[:count]
            return count

        fake_module.simplify = record_simplify
        with patch.dict(sys.modules, {"meshoptimizer": fake_module}):
            levels, _new_vertices = qt_simplifier.build_meshoptimizer_lods(
                points, normals, [(0, len(indices))], indices, highest=3, vertex_base=len(points))

        self.assertEqual(calls, [len(indices) // 2, len(indices) // 4, len(indices) // 8])
        self.assertEqual(sorted(levels), [1, 2, 3])
        assert_ccw_reduced(self, points, indices, levels)

    def test_meshoptimizer_falls_back_when_simplification_stalls(self):
        points, normals, indices = grid_data(8)
        calls = {"simplify": [], "sloppy": []}
        fake_module = ModuleType("meshoptimizer")

        def stalled_simplify(destination, source_indices, _positions, target_index_count=None, **_options):
            calls["simplify"].append(target_index_count)
            # Hit LOD1, then make slight progress while missing later targets.
            count = int(target_index_count) if len(calls["simplify"]) == 1 else int(target_index_count) * 2 - 6
            count -= count % 3
            destination[:count] = source_indices[:count]
            return count

        def simplify_sloppy(destination, source_indices, _positions, target_index_count=None,
                            target_error=None, **_options):
            calls["sloppy"].append((target_index_count, target_error))
            count = int(target_index_count) - int(target_index_count) % 3
            destination[:count] = source_indices[:count]
            return count

        fake_module.simplify = stalled_simplify
        fake_module.simplify_sloppy = simplify_sloppy
        with patch.dict(sys.modules, {"meshoptimizer": fake_module}):
            levels, _new_vertices = qt_simplifier.build_meshoptimizer_lods(
                points, normals, [(0, len(indices))], indices, highest=3, vertex_base=len(points))

        self.assertEqual(sorted(levels), [1, 2, 3])
        self.assertEqual(len(calls["sloppy"]), 2)
        self.assertTrue(all(error == 1.0 for _target, error in calls["sloppy"]))
        assert_ccw_reduced(self, points, indices, levels)

    def test_meshoptimizer_stops_when_both_simplifiers_cannot_reduce(self):
        points, normals, indices = grid_data(8)
        fake_module = ModuleType("meshoptimizer")

        def no_progress(destination, source_indices, _positions, **_options):
            destination[:] = source_indices
            return len(source_indices)

        fake_module.simplify = no_progress
        fake_module.simplify_sloppy = no_progress
        with patch.dict(sys.modules, {"meshoptimizer": fake_module}):
            levels, _new_vertices = qt_simplifier.build_meshoptimizer_lods(
                points, normals, [(0, len(indices))], indices, highest=3, vertex_base=len(points))

        self.assertEqual(levels, {})

    def test_meshoptimizer_reports_missing_optional_dependency(self):
        points, normals, indices = grid_data()
        with patch.dict(sys.modules, {"meshoptimizer": None}):
            with self.assertRaisesRegex(RuntimeError, "meshoptimizer package is not installed"):
                qt_simplifier.build_meshoptimizer_lods(
                    points, normals, [(0, len(indices))], indices, highest=1, vertex_base=len(points))

    @unittest.skipUnless(importlib.util.find_spec("meshoptimizer"), "meshoptimizer is not installed")
    def test_installed_meshoptimizer_simplifies_a_grid(self):
        points, normals, indices = grid_data(16)
        levels, _new_vertices = qt_simplifier.build_meshoptimizer_lods(
            points, normals, [(0, len(indices))], indices, highest=2, vertex_base=len(points))

        self.assertTrue(levels)
        assert_ccw_reduced(self, points, indices, levels)


if __name__ == "__main__":
    unittest.main()
