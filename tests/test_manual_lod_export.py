"""Run: Blender --background --factory-startup --python tests/test_manual_lod_export.py"""
import bmesh
import bpy
import importlib
import importlib.util
import math
import numpy as np
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

addon = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('manual_lod_export_test', addon / '__init__.py', submodule_search_locations=[str(addon)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
reader = sys.modules[spec.name + '.qt_mesh_importer']
validator = importlib.import_module(spec.name + '.qt_mesh_validate')
port = importlib.import_module(spec.name + '.qt_simplifier')

MATERIALS = [bpy.data.materials.new('MatA'), bpy.data.materials.new('MatB')]
temp_dirs = []
BASE_VERTS = 16      # 3x3 quad grid
LOD1_VERTS = 9       # 2x2 quad grid
LOD2_VERTS = 4       # single quad
BIG_VERTS = 81       # 8x8 quad grid


def grid_mesh(name, n, material_for_face=lambda i: i % 2, uv_layers=0):
    """n x n quad grid in the XY plane with two material slots."""
    verts = [(float(x), float(y), 0.0) for y in range(n + 1) for x in range(n + 1)]
    faces = []
    for y in range(n):
        for x in range(n):
            i = y * (n + 1) + x
            faces.append((i, i + 1, i + n + 2, i + n + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    for material in MATERIALS:
        mesh.materials.append(material)
    for poly in mesh.polygons:
        poly.material_index = material_for_face(poly.index)
    for k in range(uv_layers):
        mesh.uv_layers.new(name=f'UVMap{k}')
    mesh.update()
    return mesh


def make_object(name, mesh):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = (3, 4, 5)
    return obj


def configure_legacy_test_fixture(obj):
    """Translate this suite's old test fixtures into the new object panel."""
    settings = obj.qt_lod_settings
    settings.enabled = True
    for level in range(1, 8):
        source = obj.data.get(f'mesh_lod{level}')
        if isinstance(source, bpy.types.Mesh):
            source = make_object(f'FixtureLOD{level}', source)
        if isinstance(source, bpy.types.Object) and source.type == 'MESH':
            setattr(settings, f'lod{level}', source)
    custom = obj.data.get('mesh_lods_distances', obj.get('mesh_lods_distances'))
    if not isinstance(custom, str) and custom is not None:
        for index, value in enumerate(custom[:7], 1):
            setattr(settings, f'use_distance{index}', True)
            setattr(settings, f'distance{index}', value)
    limit = obj.get('mesh_lods_max', obj.data.get('mesh_lods_max'))
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        settings.use_max = True
        settings.max_levels = min(limit, 7)


def export(obj, manual=True, generate=False, legacy_fixture=True, **extra):
    if legacy_fixture:
        configure_legacy_test_fixture(obj)
    msgs = []
    settings = SimpleNamespace(
        report=lambda *args: msgs.append(' '.join(str(a) for a in args)),
        apply_modifiers=True,
        generate_lods=generate, manual_lods=manual, **{'convert_coords': True, 'generate_lod_count': 7, 'recalculate_lod_normals': True, **extra})
    out = Path(tempfile.mkdtemp(prefix='blender-manual-lod-'))
    temp_dirs.append(out)
    e = module.BalsamExporter(str(out / 'scene.qml'), settings)
    e._obj_qml(obj)
    files = list(e.mesh_dir.rglob('*.mesh'))
    assert len(files) == 1, files
    return files[0], msgs


def validate(path):
    report = validator.validate_qt_mesh(str(path))
    assert len(report['meshes']) == 1
    return report, report['meshes'][0]


def levels_of(mesh):
    return {lod['level']: lod for lod in mesh['lods']}


def test_manual_lods_embedded_in_one_mesh():
    base = grid_mesh('Grid', 3)
    base['mesh_lod1'] = grid_mesh('GridLOD1', 2)
    base['mesh_lod2'] = grid_mesh('GridLOD2', 1, lambda i: 0)
    path, _ = export(make_object('Grid', base))
    _, mesh = validate(path)
    levels = levels_of(mesh)

    assert sorted(levels) == [0, 1, 2], levels
    assert (levels[0]['vertices'], levels[0]['triangles']) == (BASE_VERTS, 18), levels[0]
    assert (levels[1]['vertices'], levels[1]['triangles']) == (LOD1_VERTS, 8), levels[1]
    assert (levels[2]['vertices'], levels[2]['triangles']) == (10, 6), levels[2]
    # Default camera ranges increase with the LOD level.
    assert 0 < levels[1]['distance'] <= levels[2]['distance'], levels
    assert mesh['vertexBufferVertices'] == BASE_VERTS + LOD1_VERTS + LOD2_VERTS

    assert sorted(sub['lodCount'] for sub in mesh['subsets']) == [1, 2], mesh['subsets']
    lod1_counts = sorted(sub['lods'][0]['count'] for sub in mesh['subsets'])
    lod2_counts = [sub['lods'][1]['count'] for sub in mesh['subsets'] if len(sub['lods']) > 1]
    assert lod1_counts == [12, 12], lod1_counts
    assert lod2_counts == [6], lod2_counts


def test_flag_off_keeps_single_lod0():
    base = grid_mesh('FlagOff', 3)
    base['mesh_lod1'] = grid_mesh('FlagOffLOD1', 2)
    path, _ = export(make_object('FlagOff', base), manual=False)
    _, mesh = validate(path)
    assert [lod['level'] for lod in mesh['lods']] == [0], mesh['lods']
    assert all(sub['lodCount'] == 0 for sub in mesh['subsets'])
    assert mesh['vertexBufferVertices'] == BASE_VERTS


def test_single_manual_lod2_keeps_its_level_slot():
    base = grid_mesh('OnlyLod2', 3)
    base['mesh_lod2'] = grid_mesh('OnlyLod2Level2', 1, lambda i: 0)
    path, _ = export(make_object('OnlyLod2', base), manual=True, generate=False)
    _, mesh = validate(path)
    levels = levels_of(mesh)

    assert sorted(levels) == [0, 1, 2], levels
    assert (levels[1]['vertices'], levels[1]['triangles']) == (BASE_VERTS, 18), levels[1]
    assert levels[1]['distance'] > 0, levels[1]
    assert (levels[2]['vertices'], levels[2]['triangles']) == (16, 10), levels[2]
    assert levels[2]['distance'] >= levels[1]['distance'], levels
    assert mesh['vertexBufferVertices'] == BASE_VERTS + LOD2_VERTS
    assert [lod['level'] for lod in mesh['lods']] == [0, 1, 2], mesh['lods']
    assert sorted(sub['lodCount'] for sub in mesh['subsets']) == [0, 2], mesh['subsets']


def test_generated_lods_unchanged_without_properties():
    legacy_path, _ = export(make_object('Plain', grid_mesh('Plain', 8)), manual=False, generate=True)
    new_path, _ = export(make_object('Plain', grid_mesh('Plain', 8)), manual=True, generate=True)
    _, legacy = validate(legacy_path)
    _, new = validate(new_path)
    legacy_counts = [sub['lodCount'] for sub in legacy['subsets']]
    assert any(count > 0 for count in legacy_counts), legacy_counts
    assert [sub['lodCount'] for sub in new['subsets']] == legacy_counts
    assert new['vertexBufferVertices'] == legacy['vertexBufferVertices']


def test_generated_lods_fill_only_missing_levels():
    base = grid_mesh('Fill', 3)
    base['mesh_lod2'] = grid_mesh('FillLOD2', 1, lambda i: 0)
    path, _ = export(make_object('Fill', base), manual=True, generate=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)

    assert (levels[2]['vertices'], levels[2]['triangles']) == (16, 10), levels[2]
    assert levels[2]['distance'] > 0, levels[2]
    assert levels[1]['triangles'] > 0, levels[1]
    assert mesh['vertexBufferVertices'] == BASE_VERTS + LOD2_VERTS
    assert [lod['level'] for lod in mesh['lods']] == [0, 1, 2], mesh['lods']
    assert sorted(sub['lodCount'] for sub in mesh['subsets']) == [0, 2], mesh['subsets']


def test_skipped_manual_lod_falls_back_to_generated():
    base = grid_mesh('Fallback', 8)
    base['mesh_lod1'] = grid_mesh('FallbackLOD1', 2, uv_layers=2)
    path, msgs = export(make_object('Fallback', base), manual=True, generate=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)

    assert mesh['vertexBufferVertices'] == BIG_VERTS, mesh['vertexBufferVertices']
    assert levels[1]['triangles'] > 0, levels[1]
    assert any('generated LOD used instead' in m for m in msgs), msgs


def test_object_datablock_property_is_accepted():
    lod_object = make_object('GridLodObject', grid_mesh('GridLodObject', 2))
    base = grid_mesh('GridObjectRef', 3)
    base['mesh_lod1'] = lod_object
    path, _ = export(make_object('GridObjectRef', base))
    _, mesh = validate(path)
    levels = levels_of(mesh)
    assert (levels[1]['vertices'], levels[1]['triangles']) == (LOD1_VERTS, 8), levels


def test_layout_mismatch_is_skipped_with_warning():
    base = grid_mesh('Mismatch', 3)
    base['mesh_lod1'] = grid_mesh('MismatchLOD1', 2, uv_layers=2)
    path, msgs = export(make_object('Mismatch', base))
    _, mesh = validate(path)
    assert [lod['level'] for lod in mesh['lods']] == [0], mesh['lods']
    assert any('vertex attributes differ' in msg for msg in msgs), msgs


def test_non_datablock_fixture_is_ignored():
    base = grid_mesh('BadProp', 3)
    base['mesh_lod2'] = 'not a mesh'
    path, msgs = export(make_object('BadProp', base))
    _, mesh = validate(path)
    assert [lod['level'] for lod in mesh['lods']] == [0], mesh['lods']
    assert not any('ERROR' in msg for msg in msgs), msgs


def test_temporary_source_objects_are_removed():
    lod1 = grid_mesh('KeepLOD1', 2)
    base = grid_mesh('KeepBase', 3)
    base['mesh_lod1'] = lod1
    export(make_object('KeepBase', base))
    leftovers = [o.name for o in bpy.data.objects if o.name.startswith('__qt_lod_tmp_')]
    assert not leftovers, leftovers
    assert len(lod1.vertices) == LOD1_VERTS


def test_importer_reads_embedded_lods():
    base = grid_mesh('RoundTrip', 3)
    base['mesh_lod1'] = grid_mesh('RoundTripLOD1', 2)
    path, _ = export(make_object('RoundTrip', base))
    meshes = reader.read_qt_mesh_file(str(path))
    mesh = meshes[0] if isinstance(meshes, (list, tuple)) else next(iter(meshes.values()))
    assert len(mesh.subsets) > 0
    for sub in mesh.subsets:
        assert len(sub.lods) == 1, sub.lods
    lod1_counts = sorted(sub.lods[0].count for sub in mesh.subsets)
    assert lod1_counts == [12, 12], lod1_counts


def test_validator_summary_text():
    base = grid_mesh('Summary', 3)
    base['mesh_lod1'] = grid_mesh('SummaryLOD1', 2)
    base['mesh_lod2'] = grid_mesh('SummaryLOD2', 1, lambda i: 0)
    path, _ = export(make_object('Summary', base))
    report, mesh = validate(path)
    text = validator.format_lod_summary(report)
    assert len(mesh['subsets']) == 2, mesh['subsets']
    for index, subset in enumerate(mesh['subsets'], start=1):
        assert f'  subset {index}:' in text, text
        for lod in subset['levels']:
            line = validator._format_level(lod, '    ')
            assert line in text, (line, text)


def bumpy_grid(name, n):
    """Single-material n x n grid with a smooth height field, so simplification has real error."""
    mesh = grid_mesh(name, n, lambda i: 0)
    for v in mesh.vertices:
        v.co.z = 0.2 * math.sin(v.co.x * 1.3) * math.cos(v.co.y * 1.7)
    mesh.update()
    return mesh


def lod0_vertices(name, base):
    path, _ = export(make_object(name, base), manual=False, generate=False)
    _, mesh = validate(path)
    return mesh['vertexBufferVertices']


def test_generated_distances_follow_camera_ranges():
    base = bumpy_grid('Bumpy', 8)
    path, _ = export(make_object('Bumpy', base), manual=False, generate=True)
    _, mesh = validate(path)
    lods = mesh['subsets'][0]['lods']
    assert len(lods) >= 2, lods
    distances = [lod['distance'] for lod in lods]
    assert distances == sorted(distances) and distances[0] > 0, distances
    factor = 2 * math.tan(math.radians(30)) / 1080
    for level, distance in enumerate(distances, 1):
        expected = module.qt_mesh_writer.LOD_CAMERA_RANGES[level - 1] * factor
        assert math.isclose(distance, expected, rel_tol=1e-6), (level, distance, expected)


def test_custom_lod_distances_property():
    base = bumpy_grid('CustomDist', 8)
    base['mesh_lods_distances'] = [700.0, 2500.0]
    path, _ = export(make_object('CustomDist', base), manual=True, generate=True)
    _, mesh = validate(path)
    lods = mesh['subsets'][0]['lods']
    factor = 2 * math.tan(math.radians(30)) / 1080
    for lod, depth in zip(lods, (700.0, 2500.0)):
        assert math.isclose(lod['distance'], depth * factor, rel_tol=1e-6), lods
    threshold = 1 / 1920
    multiplier = 2 * (1920 / 1080) * math.tan(math.radians(30))
    for level, depth in enumerate((700.0, 2500.0), 1):
        for offset, expected in ((-1, level - 1), (1, level)):
            eligible = 0
            for lod in lods:
                if lod['distance'] / ((depth + offset) * multiplier) > threshold:
                    break
                eligible += 1
            assert eligible == expected, (level, depth, offset, eligible)


def test_partial_custom_distances_preserve_camera_ranges():
    base = bumpy_grid('PartialCustomDist', 8)
    base['mesh_lods_distances'] = [700.0]
    path, _ = export(make_object('PartialCustomDist', base), manual=True, generate=True)
    _, mesh = validate(path)
    subset = mesh['subsets'][0]
    assert math.isclose(subset['lods'][0]['distance'], 700 * 2 * math.tan(math.radians(30)) / 1080, rel_tol=1e-6)
    expected = module.qt_mesh_writer.LOD_CAMERA_RANGES[1] * 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(subset['lods'][1]['distance'], expected, rel_tol=1e-6), (subset['lods'], expected)


def test_custom_lod_distances_need_manual_lods():
    base = bumpy_grid('CustomOff', 8)
    base['mesh_lods_distances'] = [1.5, 3.0]
    path, _ = export(make_object('CustomOff', base), manual=False, generate=True)
    _, mesh = validate(path)
    expected = module.qt_mesh_writer.LOD_CAMERA_RANGES[0] * 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(mesh['subsets'][0]['lods'][0]['distance'], expected, rel_tol=1e-6)


def test_custom_ranges_clamp_decreasing_values():
    base = bumpy_grid('CustomClamp', 8)
    base['mesh_lods_distances'] = [7000.0, 6000.0]
    path, msgs = export(make_object('CustomClamp', base), manual=True, generate=True)
    _, mesh = validate(path)
    lods = mesh['subsets'][0]['lods']
    assert len(lods) >= 3, lods
    expected = 7000 * 2 * math.tan(math.radians(30)) / 1080
    for lod in lods[:3]:
        assert math.isclose(lod['distance'], expected, rel_tol=1e-6), lods
    assert any('LOD2 camera distance' in m and 'clamped' in m for m in msgs), msgs
    assert any('LOD3 camera distance' in m and 'clamped' in m for m in msgs), msgs


def test_custom_ranges_override_legacy_and_scale():
    base = bumpy_grid('CustomLegacy', 8)
    obj = make_object('CustomLegacy', base)
    reference, _ = export(obj, manual=False, generate=True, lod_camera_ranges=False)
    reference_lods = validate(reference)[1]['subsets'][0]['lods']
    base['mesh_lods_distances'] = [1.0]
    path, _ = export(obj, manual=True, generate=True,
                     lod_camera_ranges=False, custom_distance_scale=2.0)
    _, mesh = validate(path)
    lods = mesh['subsets'][0]['lods']
    expected = math.tan(math.radians(30)) / 1080
    assert math.isclose(lods[0]['distance'], expected, rel_tol=1e-6), lods
    assert math.isclose(lods[1]['distance'], max(expected, reference_lods[1]['distance'] / 2), rel_tol=1e-6), lods


def test_invalid_custom_lod_distances_are_ignored_with_warning():
    base = bumpy_grid('CustomBad', 8)
    base['mesh_lods_distances'] = 'far'
    path, msgs = export(make_object('CustomBad', base), manual=True, generate=True)
    _, mesh = validate(path)
    assert not any('ERROR' in msg for msg in msgs), msgs
    assert len(mesh['lods']) >= 2, mesh['lods']


def test_nonfinite_custom_lod_distances_are_ignored():
    base = bumpy_grid('CustomNonfinite', 8)
    base['mesh_lods_distances'] = [float('nan')]
    path, msgs = export(make_object('CustomNonfinite', base), manual=True, generate=True)
    _, mesh = validate(path)
    expected = module.qt_mesh_writer.LOD_CAMERA_RANGES[0] * 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(mesh['subsets'][0]['lods'][0]['distance'], expected, rel_tol=1e-6)
    assert any('finite and non-negative' in m for m in msgs), msgs


def test_custom_lod_distances_on_object():
    base = bumpy_grid('CustomObj', 8)
    obj = make_object('CustomObj', base)
    obj['mesh_lods_distances'] = [1.5, 3.0]
    path, _ = export(obj, manual=True, generate=True)
    _, mesh = validate(path)
    for lod, depth in zip(mesh['subsets'][0]['lods'], (1.5, 3.0)):
        assert math.isclose(lod['distance'], depth * 2 * math.tan(math.radians(30)) / 1080, rel_tol=1e-6)


def test_mesh_custom_ranges_take_precedence():
    base = bumpy_grid('CustomPriority', 8)
    base['mesh_lods_distances'] = [700.0]
    obj = make_object('CustomPriority', base)
    obj['mesh_lods_distances'] = [900.0]
    path, _ = export(obj, manual=True, generate=True)
    _, mesh = validate(path)
    expected = 700 * 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(mesh['subsets'][0]['lods'][0]['distance'], expected, rel_tol=1e-6)


def test_custom_lod_distances_without_lod_levels_warn():
    base = bumpy_grid('CustomNoLods', 8)
    base['mesh_lods_distances'] = [1.5, 3.0]
    _, msgs = export(make_object('CustomNoLods', base), manual=True, generate=False)
    assert any('no LOD levels' in m for m in msgs), msgs


def test_generated_lods_reuse_lod0_vertices_without_recalc():
    base = bumpy_grid('BumpyNoRecalc', 8)
    path, _ = export(make_object('BumpyNoRecalc', base), manual=False, generate=True,
                     recalculate_lod_normals=False)
    _, mesh = validate(path)
    assert mesh['vertexBufferVertices'] == lod0_vertices('BumpyNoRecalcRef', bumpy_grid('BumpyNoRecalcRef', 8)), mesh['vertexBufferVertices']


def test_recalculated_lod_normals_split_vertices():
    base = bumpy_grid('BumpyRecalc', 8)
    path, _ = export(make_object('BumpyRecalc', base), manual=False, generate=True,
                     recalculate_lod_normals=True,
                     recalculate_lod_normals_merge_angle=60.0,
                     recalculate_lod_normals_split_angle=0.0)
    _, mesh = validate(path)
    assert mesh['vertexBufferVertices'] > lod0_vertices('BumpyRecalcRef', bumpy_grid('BumpyRecalcRef', 8)), mesh['vertexBufferVertices']
    assert len(mesh['lods']) >= 2, mesh['lods']


def closed_sphere(name, subdivisions):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(MATERIALS[0])
    mesh.update()
    return mesh


def test_camera_ranges_in_written_mesh():
    base = closed_sphere('RangeSphere', 2)
    for vertex in base.vertices:
        vertex.co *= 200
    base.update()
    for level in range(1, 8):
        base[f'mesh_lod{level}'] = closed_sphere(f'RangeSphereLOD{level}', 1)
    path, _ = export(make_object('RangeSphere', base))
    _, mesh = validate(path)
    subset = mesh['subsets'][0]
    lods = subset['lods']
    assert len(lods) == 7, lods
    half_depth = (subset['boundsMax'][2] - subset['boundsMin'][2]) / 2
    factor = 2 * math.tan(math.radians(30)) / 1080
    pixel_threshold = 1 / 1920
    fov_multiplier = 2 * (1920 / 1080) * math.tan(math.radians(30))

    def selected_lod(depth):
        result = 0
        for index, lod in enumerate(lods):
            screen_size = lod['distance'] / ((depth - half_depth) * fov_multiplier)
            if screen_size > pixel_threshold:
                break
            result = index + 1
        return result

    for level, (lod, target) in enumerate(zip(lods, module.qt_mesh_writer.LOD_CAMERA_RANGES), 1):
        expected = target * factor
        assert math.isclose(lod['distance'], expected, rel_tol=1e-6), (level, lod, expected)
        assert selected_lod(target + half_depth - 1) == level - 1, (level, target, lods)
        assert selected_lod(target + half_depth + 1) == level, (level, target, lods)


def test_camera_ranges_measure_each_subset_surface():
    base = grid_mesh('RangeSubsets', 3, material_for_face=lambda i: 0 if i % 3 == 0 else 1)
    for vertex in base.vertices:
        vertex.co.z = vertex.co.x * 10
    base.update()
    base['mesh_lod1'] = grid_mesh('RangeSubsetsLOD1', 2)
    path, _ = export(make_object('RangeSubsets', base), generate=False, convert_coords=False)
    _, mesh = validate(path)
    factor = 2 * math.tan(math.radians(30)) / 1080
    assert mesh['subsets'][0]['boundsMax'][2] - mesh['subsets'][0]['boundsMin'][2] != (
        mesh['subsets'][1]['boundsMax'][2] - mesh['subsets'][1]['boundsMin'][2])
    for subset in mesh['subsets']:
        assert math.isclose(subset['lods'][0]['distance'], 500 * factor, rel_tol=1e-6)


def test_known_surface_distances():
    for level, depth in enumerate(module.qt_mesh_writer.LOD_CAMERA_RANGES, 1):
        expected = depth * 2 * math.tan(math.radians(30)) / 1080
        assert math.isclose(module.qt_mesh_writer._camera_lod_distance(depth), expected, abs_tol=0.000001)


def test_large_bounds_keep_surface_distance():
    base = closed_sphere('HugeRangeSphere', 1)
    for vertex in base.vertices:
        vertex.co *= 1000
    base.update()
    base['mesh_lod1'] = closed_sphere('HugeRangeSphereLOD1', 1)
    path, msgs = export(make_object('HugeRangeSphere', base))
    _, mesh = validate(path)
    assert math.isclose(mesh['subsets'][0]['lods'][0]['distance'],
                        500 * 2 * math.tan(math.radians(30)) / 1080, rel_tol=1e-6)
    assert not any('transition cannot be represented' in message for message in msgs), msgs


def test_legacy_distance_policy_is_available():
    base = bumpy_grid('LegacyDistance', 8)
    _, mesh = validate(export(make_object('LegacyDistance', base), manual=False, generate=True,
                              lod_camera_ranges=False)[0])
    subset = mesh['subsets'][0]
    expected = module.qt_mesh_writer._camera_lod_distance(module.qt_mesh_writer.LOD_CAMERA_RANGES[0])
    assert not math.isclose(subset['lods'][0]['distance'], expected, rel_tol=1e-5)


def test_manual_distances_match_generated_for_both_policies():
    base = closed_sphere('CompareManualAuto', 3)
    for vertex in base.vertices:
        vertex.co *= 200
    base.update()
    for level in range(1, 4):
        manual = closed_sphere(f'CompareManualAutoLOD{level}', 1)
        for vertex in manual.vertices:
            vertex.co *= 200
        manual.update()
        base[f'mesh_lod{level}'] = manual
    obj = make_object('CompareManualAuto', base)
    for camera_ranges in (True, False):
        auto_path, _ = export(obj, manual=False, generate=True, generate_lod_count=3,
                              lod_camera_ranges=camera_ranges)
        manual_path, _ = export(obj, manual=True, generate=False, lod_camera_ranges=camera_ranges)
        mixed_path, _ = export(obj, manual=True, generate=True, generate_lod_count=1,
                               lod_camera_ranges=camera_ranges)
        auto = validate(auto_path)[1]['subsets'][0]['lods']
        manual = validate(manual_path)[1]['subsets'][0]['lods']
        mixed = validate(mixed_path)[1]['subsets'][0]['lods']
        assert len(auto) == len(manual) == len(mixed) == 3, (auto, manual, mixed)
        for generated, selected, combined in zip(auto, manual, mixed):
            assert math.isclose(selected['distance'], generated['distance'], rel_tol=1e-6), (auto, manual)
            assert math.isclose(combined['distance'], generated['distance'], rel_tol=1e-6), (auto, mixed)
        assert manual[0]['count'] != auto[0]['count'], (manual, auto)


def test_manual_legacy_missing_simplification_warns_and_uses_ranges():
    base = grid_mesh('ManualSmall', 1, lambda i: 0)
    base['mesh_lod1'] = grid_mesh('ManualSmallLOD1', 1, lambda i: 0)
    path, msgs = export(make_object('ManualSmall', base), manual=True, generate=False,
                        lod_camera_ranges=False)
    lod = validate(path)[1]['subsets'][0]['lods'][0]
    expected = module.qt_mesh_writer.LOD_CAMERA_RANGES[0] * 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(lod['distance'], expected, rel_tol=1e-6), lod
    assert any('no automatic simplification distance' in msg for msg in msgs), msgs


def test_small_subset_uses_largest_subset_distance_and_omits_empty_levels():
    base = bumpy_grid('FallbackMain', 8)
    base.polygons[0].material_index = 1
    base.update()
    lod1 = grid_mesh('FallbackMainLOD1', 3, lambda i: 1 if i == 0 else 0)
    lod2 = grid_mesh('FallbackMainLOD2', 2, lambda i: 0)
    lod3 = grid_mesh('FallbackMainLOD3', 1, lambda i: 0)
    base['mesh_lod1'] = lod1
    base['mesh_lod2'] = lod2
    base['mesh_lod3'] = lod3
    path, msgs = export(make_object('FallbackMain', base), manual=True, generate=False,
                        lod_camera_ranges=False)
    _, mesh = validate(path)
    main, small = mesh['subsets']
    assert len(main['lods']) >= 1 and len(small['lods']) == 1, mesh['subsets']
    assert small['lods'][0]['count'] == 6, small
    assert math.isclose(small['lods'][0]['distance'], main['lods'][0]['distance'], rel_tol=1e-6)
    assert not any('subset_1' in msg and 'no automatic simplification distance' in msg for msg in msgs), msgs
    assert all(lod['count'] > 0 for subset in mesh['subsets'] for lod in subset['lods'])


def test_missing_middle_subset_keeps_previous_range():
    base = grid_mesh('MissingMiddle', 3, lambda i: i % 2)
    base['mesh_lod1'] = grid_mesh('MissingMiddleLOD1', 2, lambda i: i % 2)
    base['mesh_lod2'] = grid_mesh('MissingMiddleLOD2', 2, lambda i: 0)
    base['mesh_lod3'] = grid_mesh('MissingMiddleLOD3', 2, lambda i: i % 2)
    path, _ = export(make_object('MissingMiddle', base))
    _, mesh = validate(path)
    small = mesh['subsets'][1]
    assert len(small['lods']) == 3, small
    first, middle, last = small['lods']
    assert first['count'] > 0 and last['count'] > 0, small
    assert (middle['count'], middle['offset']) == (first['count'], first['offset']), small
    assert middle['distance'] == last['distance'], small
    assert all(lod['count'] > 0 for subset in mesh['subsets'] for lod in subset['lods'])


def test_small_subset_reuses_each_largest_subset_distance():
    base = bumpy_grid('FallbackEvery', 8)
    base.polygons[0].material_index = 1
    base.update()
    for level in range(1, 4):
        base[f'mesh_lod{level}'] = grid_mesh(f'FallbackEveryLOD{level}', 3, lambda i: 1 if i == 0 else 0)
    path, msgs = export(make_object('FallbackEvery', base), manual=True, generate=False,
                        lod_camera_ranges=False)
    _, mesh = validate(path)
    main, small = mesh['subsets']
    assert len(main['lods']) == len(small['lods']) == 3, mesh['subsets']
    for main_lod, small_lod in zip(main['lods'], small['lods']):
        assert math.isclose(small_lod['distance'], main_lod['distance'], rel_tol=1e-6), mesh['subsets']
        assert small_lod['count'] > 0
    assert not any('subset_1' in msg and 'no automatic simplification distance' in msg for msg in msgs), msgs


def test_manual_custom_camera_ranges_are_preserved():
    base = closed_sphere('ManualCustomRange', 2)
    base['mesh_lod1'] = closed_sphere('ManualCustomRangeLOD1', 1)
    base['mesh_lod2'] = closed_sphere('ManualCustomRangeLOD2', 1)
    base['mesh_lods_distances'] = [750.0, 3000.0]
    path, _ = export(make_object('ManualCustomRange', base), manual=True, generate=False,
                     lod_camera_ranges=False, custom_distance_scale=2.0)
    lods = validate(path)[1]['subsets'][0]['lods']
    assert len(lods) == 2, lods
    for lod, depth in zip(lods, (750.0, 3000.0)):
        expected = depth * math.tan(math.radians(30)) / 1080
        assert math.isclose(lod['distance'], expected, rel_tol=1e-6), lods


def test_levels_decrease_and_distances_grow():
    path, _ = export(make_object('Sphere', closed_sphere('Sphere', 3)), manual=False, generate=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)
    level_ids = [k for k in sorted(levels) if k > 0]
    assert len(level_ids) >= 2, mesh['lods']
    counts = [levels[k]['triangles'] for k in level_ids]
    assert all(later <= earlier for earlier, later in zip(counts, counts[1:])), counts
    distances = [levels[k]['distance'] for k in level_ids]
    assert distances == sorted(distances), distances


def test_port_levels_of_detail_distances():
    points, normals, indices = sphere_arrays(3)
    lods = port.levels_of_detail(points, indices, normals)
    distances = [float(d) for d, _ in lods][::-1]
    assert len(distances) >= 2 and distances == sorted(distances) and distances[0] > 0, distances


def test_vertex_caps_mode_fits_caps():
    path, _ = export(make_object('Caps', closed_sphere('Caps', 3)), manual=False, generate=True,
                     lod_vertex_caps=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)
    assert [lod['level'] for lod in mesh['lods']] == [0, 1, 2, 3], mesh['lods']
    for k, cap in zip((1, 2, 3), (81, 40, 20)):
        assert 0 < levels[k]['vertices'] <= cap, (k, levels[k], cap)
    distances = [levels[k]['distance'] for k in (1, 2, 3)]
    assert distances == sorted(distances), distances


def test_generated_lods_without_recalc_on_flat_mesh():
    mesh = closed_sphere('FlatNoRecalc', 3)
    for poly in mesh.polygons:
        poly.use_smooth = False
    mesh.update()
    path, _ = export(make_object('FlatNoRecalc', mesh), manual=False, generate=True,
                     recalculate_lod_normals=False)
    _, rep = validate(path)
    assert len(rep['lods']) >= 2, rep['lods']
    assert rep['lods'][1]['triangles'] < rep['lods'][0]['triangles'], rep['lods']


def test_small_subset_gets_no_generated_levels():
    base = grid_mesh('SmallSubset', 8, material_for_face=lambda i: 1 if i == 0 else 0)
    path, _ = export(make_object('SmallSubset', base), manual=False, generate=True)
    _, mesh = validate(path)
    assert len(mesh['subsets']) == 2, mesh['subsets']
    assert len(mesh['subsets'][0]['lods']) >= 2, mesh['subsets'][0]
    assert mesh['subsets'][1]['lods'] == [], mesh['subsets'][1]


def test_custom_distance_scale_divides_distances():
    _, plain = validate(export(make_object('ScaleB', bumpy_grid('ScaleB', 8)), manual=False, generate=True)[0])
    path, _ = export(make_object('ScaleA', bumpy_grid('ScaleA', 8)), manual=False, generate=True,
                     custom_distance_scale=100.0)
    _, scaled = validate(path)
    plain_lods = plain['subsets'][0]['lods']
    scaled_lods = scaled['subsets'][0]['lods']
    assert len(plain_lods) == len(scaled_lods) >= 2, (plain_lods, scaled_lods)
    for a, b in zip(plain_lods, scaled_lods):
        assert abs(a['distance'] / 100.0 - b['distance']) <= 1e-5 * b['distance'] + 1e-9, (a, b)


def test_generate_lod_count_stops_early():
    path, _ = export(make_object('Stop', grid_mesh('Stop', 8)), manual=False, generate=True,
                     generate_lod_count=1)
    _, mesh = validate(path)
    assert [lod['level'] for lod in mesh['lods']] == [0, 1], mesh['lods']


def test_mesh_lods_max_limits_generated_levels():
    base = closed_sphere('ObjectLimit', 3)
    obj = make_object('ObjectLimit', base)
    obj['mesh_lods_max'] = 1
    path, _ = export(obj, manual=True, generate=True, generate_lod_count=3)
    _, mesh = validate(path)
    assert [lod['level'] for lod in mesh['lods']] == [0, 1], mesh['lods']


def test_mesh_lods_max_zero_keeps_manual_levels():
    base = closed_sphere('ZeroLimit', 3)
    base['mesh_lod3'] = closed_sphere('ZeroLimitLOD3', 1)
    obj = make_object('ZeroLimit', base)
    obj['mesh_lods_max'] = 0
    path, _ = export(obj, manual=True, generate=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)
    assert [levels[n]['triangles'] for n in (1, 2)] == [levels[0]['triangles']] * 2, levels
    assert levels[3]['triangles'] < levels[0]['triangles'], levels
    path, _ = export(obj, manual=False, generate=True)
    _, mesh = validate(path)
    assert len(mesh['lods']) > 1, mesh['lods']


def test_mesh_lods_max_combines_with_manual_levels():
    base = closed_sphere('MixedLimit', 3)
    base['mesh_lod3'] = closed_sphere('MixedLimitLOD3', 1)
    base['mesh_lods_max'] = 1
    path, _ = export(make_object('MixedLimit', base), manual=True, generate=True)
    _, mesh = validate(path)
    levels = levels_of(mesh)
    assert levels[1]['triangles'] < levels[0]['triangles'], levels
    assert levels[2]['triangles'] == levels[1]['triangles'], levels
    assert levels[3]['triangles'] < levels[2]['triangles'], levels


def test_panel_max_obeys_global_limit():
    base = closed_sphere('Limits', 3)
    obj = make_object('Limits', base)
    obj.qt_lod_settings.enabled = True
    obj.qt_lod_settings.use_max = True
    obj.qt_lod_settings.max_levels = 1
    path, _ = export(obj, manual=True, generate=True, generate_lod_count=2, legacy_fixture=False)
    assert len(validate(path)[1]['lods']) == 2
    obj.qt_lod_settings.max_levels = 7
    path, _ = export(obj, manual=True, generate=True, generate_lod_count=2, legacy_fixture=False)
    assert len(validate(path)[1]['lods']) == 3
    path, _ = export(obj, manual=False, generate=False, legacy_fixture=False)
    assert len(validate(path)[1]['lods']) == 1


def test_mesh_lods_max_shared_mesh_objects_export_independently():
    base = closed_sphere('SharedLimit', 3)
    obj1 = make_object('SharedLimit1', base)
    obj2 = make_object('SharedLimit2', base)
    obj1['mesh_lods_max'] = 0
    obj2['mesh_lods_max'] = 1
    configure_legacy_test_fixture(obj1)
    configure_legacy_test_fixture(obj2)
    settings = SimpleNamespace(report=lambda *args: None, apply_modifiers=True, convert_coords=True,
                               generate_lods=True, manual_lods=True, generate_lod_count=3)
    out = Path(tempfile.mkdtemp(prefix='blender-lod-limit-'))
    temp_dirs.append(out)
    exporter = module.BalsamExporter(str(out / 'scene.qml'), settings)
    exporter._obj_qml(obj1)
    exporter._obj_qml(obj2)
    files = list(exporter.mesh_dir.rglob('*.mesh'))
    assert len(files) == 2, files
    assert sorted(len(validate(path)[1]['lods']) for path in files) == [1, 2]


def sphere_arrays(subdivisions):
    mesh = closed_sphere('SphereArrays', subdivisions)
    points = np.array([tuple(v.co) for v in mesh.vertices], dtype=float)
    normals = np.array([tuple(v.normal) for v in mesh.vertices], dtype=float)
    indices = [i for poly in mesh.polygons for i in poly.vertices]
    return points, normals, indices


def clear_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def export_scene():
    out = Path(tempfile.mkdtemp(prefix='blender-lm-import-'))
    temp_dirs.append(out)
    settings = SimpleNamespace(
        report=lambda *args: None, apply_modifiers=True, convert_coords=True,
        generate_lods=False, manual_lods=True, export_animations=False,
        export_cameras=False, export_lights=False)
    e = module.BalsamExporter(str(out / 'scene.qml'), settings)
    e.export()
    return out


def test_logic_module_detection():
    assert module.uses_logic_module('Flag { meshSource: "a" }\nLM.FlagMaterial {}')
    assert module.uses_logic_module('    LM.SpatialSound {')
    assert not module.uses_logic_module('Node { objectName: "ELM.x" }')
    assert not module.uses_logic_module('Node { objectName: "LMx" }')
    assert not module.uses_logic_module('')


def test_scene_omits_logic_module_import_without_lm_objects():
    clear_scene()
    make_object('Plain', grid_mesh('Plain', 3))
    qml = (export_scene() / 'scene.qml').read_text(encoding='utf-8')
    assert 'import LogicModule as LM' not in qml, qml
    assert 'import "."' in qml, qml


def test_scene_imports_logic_module_when_lm_objects_exported():
    clear_scene()
    obj = make_object('Flag', grid_mesh('Flag', 3))
    obj.modifiers.new('SailingCloth', 'CLOTH')
    bpy.context.view_layer.update()
    qml = (export_scene() / 'scene.qml').read_text(encoding='utf-8')
    assert 'LM.Flag {' in qml, qml
    assert 'import LogicModule as LM' in qml, qml
    assert qml.index('import LogicModule as LM') < qml.index('import "."'), qml


def test_collection_component_import_follows_lm_usage():
    clear_scene()
    scene = bpy.context.scene
    plain_col = bpy.data.collections.new('PlainPart')
    scene.collection.children.link(plain_col)
    plain_col.objects.link(bpy.data.objects.new('PlainInPart', grid_mesh('PlainInPart', 3)))
    lm_col = bpy.data.collections.new('FlagPart')
    scene.collection.children.link(lm_col)
    flag = bpy.data.objects.new('FlagInPart', grid_mesh('FlagInPart', 3))
    lm_col.objects.link(flag)
    flag.modifiers.new('SailingCloth', 'CLOTH')
    for name, col in (('PlainInst', plain_col), ('FlagInst', lm_col)):
        inst = bpy.data.objects.new(name, None)
        inst.instance_type = 'COLLECTION'
        inst.instance_collection = col
        scene.collection.objects.link(inst)
    bpy.context.view_layer.update()
    out = export_scene()
    plain = [p for p in out.glob('*.qml') if p.stem.lower().startswith('plainpart')]
    flag_file = [p for p in out.glob('*.qml') if p.stem.lower().startswith('flagpart')]
    assert plain and flag_file, sorted(p.name for p in out.glob('*.qml'))
    assert 'import LogicModule as LM' not in plain[0].read_text(encoding='utf-8')
    assert 'import LogicModule as LM' in flag_file[0].read_text(encoding='utf-8')


if __name__ == '__main__':
    module.lod_settings_register()
    try:
        for name, fn in list(globals().items()):
            if name.startswith('test_') and callable(fn):
                fn()
                print(f'PASS {name}')
        print('manual LOD export tests passed')
    finally:
        module.lod_settings_unregister()
        for d in temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
