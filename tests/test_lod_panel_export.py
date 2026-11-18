"""Run: blender --background --factory-startup --python-exit-code 1 --python tests/test_lod_panel_export.py"""
import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

spec = importlib.util.spec_from_file_location('lod_panel_tests', Path(__file__).with_name('test_manual_lod_export.py'))
t = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = t
spec.loader.exec_module(t)
t.module.lod_settings_register()
lod_ui = sys.modules[t.module.__name__ + '.qt_lod_settings']


def lod_object(name, subdivisions=1):
    return t.make_object(name, t.closed_sphere(name, subdivisions))


def mesh_for(obj, **options):
    path, messages = t.export(obj, legacy_fixture=False, **options)
    return t.validate(path)[1], messages


def test_panel_registration_and_empty_fallback():
    obj = lod_object('EmptyPanel', 3)
    assert lod_ui.OBJECT_PT_qt_lod_settings.poll(SimpleNamespace(object=obj))
    for enabled in (False, True):
        obj.qt_lod_settings.enabled = enabled
        mesh, _ = mesh_for(obj, manual=True, generate=True, generate_lod_count=2)
        assert len(mesh['subsets'][0]['lods']) == 2, mesh
    assert not lod_ui.OBJECT_PT_qt_lod_settings.poll(SimpleNamespace(object=None))


def test_panel_manual_cap_and_distances():
    obj = lod_object('PanelManual', 3)
    settings = obj.qt_lod_settings
    settings.enabled = True
    settings.use_max = True
    settings.max_levels = 1
    settings.lod2 = lod_object('PanelManualLOD2')
    settings.use_distance1 = True
    settings.distance1 = 700
    settings.use_distance2 = True
    settings.distance2 = 3000
    mesh, _ = mesh_for(obj, manual=True, generate=True, generate_lod_count=3)
    lods = mesh['subsets'][0]['lods']
    assert len(lods) == 2, lods
    assert lods[1]['count'] == 60, lods
    factor = 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(lods[0]['distance'], 700 * factor, rel_tol=1e-6), lods
    assert math.isclose(lods[1]['distance'], 3000 * factor, rel_tol=1e-6), lods
    settings.use_max = False
    mesh, _ = mesh_for(obj, manual=True, generate=True, generate_lod_count=3)
    assert len(mesh['subsets'][0]['lods']) == 3, mesh


def test_disabled_and_legacy_properties_are_ignored():
    obj = lod_object('DisabledPanel', 3)
    settings = obj.qt_lod_settings
    settings.lod1 = lod_object('DisabledPanelLOD1')
    settings.use_max = True
    settings.max_levels = 0
    obj['mesh_lods_max'] = 0
    obj.data['mesh_lods_distances'] = [90000.0]
    obj.data['mesh_lod1'] = settings.lod1.data
    for enabled, manual in ((False, True), (True, False)):
        settings.enabled = enabled
        mesh, _ = mesh_for(obj, manual=manual, generate=True, generate_lod_count=2)
        lods = mesh['subsets'][0]['lods']
        assert len(lods) == 2 and lods[0]['count'] != 60, lods
        expected = 500 * 2 * math.tan(math.radians(30)) / 1080
        assert math.isclose(lods[0]['distance'], expected, rel_tol=1e-6), lods
    settings.enabled = False
    mesh, _ = mesh_for(obj, manual=True, generate=False)
    assert len(mesh['subsets'][0]['lods']) == 0, mesh


def test_zero_cap_and_shared_mesh():
    base = t.closed_sphere('PanelShared', 3)
    first = t.make_object('PanelSharedFirst', base)
    second = t.make_object('PanelSharedSecond', base)
    for obj, cap in ((first, 0), (second, 1)):
        obj.qt_lod_settings.enabled = True
        obj.qt_lod_settings.use_max = True
        obj.qt_lod_settings.max_levels = cap
    import tempfile
    out = Path(tempfile.mkdtemp(prefix='blender-lod-panel-'))
    t.temp_dirs.append(out)
    settings = SimpleNamespace(report=lambda *args: None, apply_modifiers=True, convert_coords=True,
                               generate_lods=True, manual_lods=True, generate_lod_count=3)
    exporter = t.module.BalsamExporter(str(out / 'scene.qml'), settings)
    exporter._obj_qml(first)
    exporter._obj_qml(second)
    files = list(exporter.mesh_dir.rglob('*.mesh'))
    assert len(files) == 2, files
    assert sorted(len(t.validate(path)[1]['subsets'][0]['lods']) for path in files) == [0, 1]


def test_sparse_distance_override_and_invalid_source():
    obj = lod_object('PanelSparse', 3)
    s = obj.qt_lod_settings
    s.enabled = True
    s.lod1 = obj
    s.use_distance2 = True
    s.distance2 = 3000
    mesh, messages = mesh_for(obj, manual=True, generate=True, generate_lod_count=3)
    lods = mesh['subsets'][0]['lods']
    assert any("points to the object's own mesh" in msg for msg in messages), messages
    factor = 2 * math.tan(math.radians(30)) / 1080
    assert math.isclose(lods[0]['distance'], 500 * factor, rel_tol=1e-6), lods
    assert math.isclose(lods[1]['distance'], 3000 * factor, rel_tol=1e-6), lods


def test_settings_survive_save_and_reload():
    import tempfile
    obj = lod_object('PersistPanel', 3)
    obj.qt_lod_settings.enabled = True
    obj.qt_lod_settings.use_max = True
    obj.qt_lod_settings.max_levels = 2
    obj.qt_lod_settings.lod1 = lod_object('PersistPanelLOD1')
    obj.qt_lod_settings.use_distance1 = True
    obj.qt_lod_settings.distance1 = 1234
    folder = Path(tempfile.mkdtemp(prefix='blender-lod-persist-'))
    t.temp_dirs.append(folder)
    filename = folder / 'settings.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(filename))
    bpy.ops.wm.open_mainfile(filepath=str(filename))
    restored = bpy.data.objects['PersistPanel'].qt_lod_settings
    assert restored.enabled and restored.use_max and restored.max_levels == 2
    assert restored.lod1.name == 'PersistPanelLOD1'
    assert restored.use_distance1 and restored.distance1 == 1234


if __name__ == '__main__':
    try:
        for name, fn in list(globals().items()):
            if name.startswith('test_') and callable(fn):
                fn()
                print('PASS', name)
        print('LOD panel export tests passed')
    finally:
        t.module.lod_settings_unregister()
        for directory in t.temp_dirs:
            t.shutil.rmtree(directory, ignore_errors=True)
