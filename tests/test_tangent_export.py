"""Run: blender --background --factory-startup --python-exit-code 1 --python tests/test_tangent_export.py"""
import importlib.util
import math
import sys
from pathlib import Path

import bpy

spec = importlib.util.spec_from_file_location('tangent_tests', Path(__file__).with_name('test_manual_lod_export.py'))
t = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t
spec.loader.exec_module(t)
t.module.lod_settings_register()


def export_mesh(obj, **options):
    path, messages = t.export(obj, legacy_fixture=False, **options)
    return t.validate(path)[1], messages


def attribute_names(mesh):
    return {entry['name'] for entry in mesh['attributes']}


def check_attributes(mesh, enabled):
    names = attribute_names(mesh)
    assert {'attr_pos', 'attr_norm', 'attr_uv0'} <= names, names
    assert ('attr_textan' in names) == enabled, names
    assert ('attr_binormal' in names) == enabled, names


def test_default_and_enabled_geometry():
    base = t.grid_mesh('TangentGrid', 3, uv_layers=1)
    uv = base.uv_layers.active.data
    for loop in base.loops:
        pos = base.vertices[loop.vertex_index].co
        uv[loop.index].uv = (pos.x / 3, pos.y / 3)
    obj = t.make_object('TangentGrid', base)
    default, _ = export_mesh(obj, manual=False, generate=False)
    disabled, _ = export_mesh(obj, manual=False, generate=False, export_tangents=False)
    enabled, _ = export_mesh(obj, manual=False, generate=False, export_tangents=True)
    check_attributes(default, False)
    check_attributes(disabled, False)
    check_attributes(enabled, True)
    assert enabled['mesh']['stride'] == default['mesh']['stride'] + 24
    assert enabled['lods'][0]['triangles'] == default['lods'][0]['triangles']


def test_enabled_without_uv_uses_existing_fallback():
    obj = t.make_object('NoUvTangent', t.grid_mesh('NoUvTangent', 2))
    mesh, _ = export_mesh(obj, manual=False, generate=False, export_tangents=True)
    check_attributes(mesh, True)


def test_manual_and_generated_lod_layouts():
    obj = t.make_object('TangentLOD', t.closed_sphere('TangentLOD', 3))
    lod = t.make_object('TangentLOD1', t.closed_sphere('TangentLOD1', 1))
    obj.qt_lod_settings.enabled = True
    obj.qt_lod_settings.lod1 = lod
    for enabled in (False, True):
        mesh, messages = export_mesh(obj, manual=True, generate=True, generate_lod_count=2,
                                     export_tangents=enabled)
        check_attributes(mesh, enabled)
        assert len(mesh['subsets'][0]['lods']) >= 2, mesh
        assert mesh['subsets'][0]['lods'][0]['count'] == 60, mesh
        assert not any('vertex attributes differ' in message for message in messages), messages


def test_real_tangent_basis():
    base = t.grid_mesh('UVBasis', 1, lambda i: 0, uv_layers=1)
    for loop in base.loops:
        pos = base.vertices[loop.vertex_index].co
        base.uv_layers.active.data[loop.index].uv = (pos.x, pos.y)
    obj = t.make_object('UVBasis', base)
    writer = sys.modules[t.module.__name__ + '.qt_mesh_writer']
    data = writer.extract_mesh_data(obj, True, False, export_tangents=True)
    tangent = writer._attribute_array(data, writer.ATTR_TANGENT, 3)
    binormal = writer._attribute_array(data, writer.ATTR_BINORMAL, 3)
    assert all(math.isclose(abs(row[0]), 1.0, abs_tol=1e-5) for row in tangent), tangent
    assert all(math.isclose(abs(row[1]), 1.0, abs_tol=1e-5) for row in binormal), binormal


if __name__ == '__main__':
    try:
        for name, fn in list(globals().items()):
            if name.startswith('test_') and callable(fn):
                fn()
                print('PASS', name)
        print('tangent export tests passed')
    finally:
        t.module.lod_settings_unregister()
        for directory in t.temp_dirs:
            t.shutil.rmtree(directory, ignore_errors=True)
