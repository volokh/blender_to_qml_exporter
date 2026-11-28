"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.py."""
import ast
import importlib.util
import math
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'hatch_initial_transform_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
hatch_module = sys.modules[spec.name + '.shipmate.qt_hatch']
gauge_module = sys.modules[spec.name + '.shipmate.qt_animated_gauge']
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

parent = bpy.data.objects.new('ControlledNode', None)
hatch = bpy.data.objects.new('Hatch', None)
hatch['qml_type'] = 'Qml.Hatch'
hatch.parent = parent
for obj in [parent, hatch]:
    bpy.context.scene.collection.objects.link(obj)
parent.location = (90, 80, 70)
parent.rotation_euler = (0.7, 0.3, -0.5)
settings = SimpleNamespace(
    report=lambda *_args: None, convert_coords=True, export_animations=False,
    export_lights=False, export_cameras=False, apply_modifiers=False,
    generate_lods=False, manual_lods=False,
)


def vector(text, name):
    matches = re.findall(r'^\s*' + name + r': Qt.vector3d(\([^\n]+\))$', text, re.MULTILINE)
    assert len(matches) == 1, (name, text)
    return ast.literal_eval(matches[0])


def close(actual, expected):
    assert all(abs(a - b) < 1e-4 for a, b in zip(actual, expected)), (actual, expected)


with tempfile.TemporaryDirectory(prefix='blender-hatch-initial-') as folder:
    exporter = addon.BalsamExporter(str(Path(folder) / 'Scene.qml'), settings)

    def export():
        bpy.context.view_layer.update()
        return '\n'.join(exporter._obj_qml(hatch, d=0))

    text = export()
    assert 'initialPosition:' not in text and 'initialRotation:' not in text, text
    for convert in [True, False]:
        settings.convert_coords = convert
        hatch.location = (1, 2, 3)
        text = export()
        close(vector(text, 'initialPosition'), (1, 3, -2) if convert else (1, 2, 3))
        assert 'initialRotation:' not in text, text
        hatch.location = (0, 0, 0)
        hatch.rotation_euler = (math.radians(30), 0, 0)
        text = export()
        close(vector(text, 'initialRotation'), (30, 0, 0))
        assert 'initialPosition:' not in text, text
        hatch.location = (1, 2, 3)
        hatch.rotation_euler = tuple(math.radians(v) for v in (20, 35, -45))
        text = export()
        position, rotation, _ = addon.qt_local_trs(hatch, convert)
        close(vector(text, 'initialPosition'), position)
        close(vector(text, 'initialRotation'), rotation)
        direct = '\n'.join(hatch_module.export_qml_hatch(
            hatch, addon.ShipmateExportContext(
                node_id='hatch', depth=0, convert_coords=convert)))
        close(vector(direct, 'initialPosition'), position)
        close(vector(direct, 'initialRotation'), rotation)
        assert 'node: parent' in text, text
        assert 'finalPosition: Qt.vector3d(0.0, 0.0, -0.0)' in text, text
        hatch.rotation_euler = (0, 0, 0)

    for mode in ['QUATERNION', 'AXIS_ANGLE']:
        hatch.rotation_mode = mode
        if mode == 'QUATERNION':
            from mathutils import Quaternion
            hatch.rotation_quaternion = Quaternion((0, 0, 1), math.radians(30))
        else:
            hatch.rotation_axis_angle = (math.radians(30), 0, 0, 1)
        close(vector(export(), 'initialRotation'), (0, 0, 30))
    hatch.rotation_mode = 'XYZ'
    hatch.rotation_euler = (0, 0, 0)

    hatch['self.initialPosition'] = 'Qt.vector3d(4, 5, 6)'
    hatch['self.initialRotation'] = 'Qt.vector3d(7, 8, 9)'
    text = export()
    close(vector(text, 'initialPosition'), (4, 5, 6))
    close(vector(text, 'initialRotation'), (7, 8, 9))
    del hatch['self.initialPosition']
    del hatch['self.initialRotation']

    collection = bpy.data.collections.new('HatchCollection')
    for obj in [parent, hatch]:
        bpy.context.scene.collection.objects.unlink(obj)
        collection.objects.link(obj)
    instance = bpy.data.objects.new('HatchInstance', None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = collection
    instance.location = (1000, 2000, 3000)
    bpy.context.scene.collection.objects.link(instance)
    bpy.context.view_layer.update()
    assert exporter.export() == {'FINISHED'}
    component = (Path(folder) / 'HatchCollection.qml').read_text()
    close(vector(component, 'initialPosition'), (1, 2, 3))
    assert 'initialRotation:' not in component, component

    gauge = bpy.data.objects.new('Gauge', None)
    gauge['qml_type'] = 'Qml.AnimatedGauge'
    gauge['change_grade'] = (1.0, 0.0, 0.0)
    gauge.parent = parent
    collection.objects.link(gauge)

    def export_gauge():
        bpy.context.view_layer.update()
        return '\n'.join(exporter._obj_qml(gauge, d=0))

    assert 'initialOffset:' not in export_gauge()
    gauge.location = (4, 5, 6)
    for convert in [True, False]:
        settings.convert_coords = convert
        text = export_gauge()
        close(vector(text, 'initialOffset'), (4, 6, -5) if convert else (4, 5, 6))
        direct = '\n'.join(gauge_module.export_qml_animated_gauge(
            gauge, addon.ShipmateExportContext(
                node_id='gauge', depth=0, convert_coords=convert)))
        close(vector(direct, 'initialOffset'), (4, 6, -5) if convert else (4, 5, 6))
        assert 'initialPosition:' not in text and 'initialRotation:' not in text, text
    gauge['self.initialOffset'] = 'Qt.vector3d(7, 8, 9)'
    close(vector(export_gauge(), 'initialOffset'), (7, 8, 9))
    del gauge['self.initialOffset']
    exporter = addon.BalsamExporter(str(Path(folder) / 'GaugeScene.qml'), settings)
    assert exporter.export() == {'FINISHED'}
    component = (Path(folder) / 'HatchCollection.qml').read_text()
    close(vector(component, 'initialOffset'), (4, 5, 6))

print('HATCH_INITIAL_TRANSFORM_EXPORT_TESTS_OK')
