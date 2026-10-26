"""Blender integration regression for Qml.PropertyAnimation markers."""
import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

root = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == 'tests' else Path('/Users/konstantin.volokh/Library/Application Support/Blender/5.2/scripts/addons/qt_balsam_exporter')
out = Path(sys.argv[sys.argv.index('--') + 1])
out.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('animation_export_test', root / '__init__.py', submodule_search_locations=[str(root)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
module = sys.modules[spec.name + '.shipmate.qt_property_animation']
addon.register()
try:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    parent = bpy.context.object
    parent.name = 'AnimatedMotor'
    bpy.ops.object.add_qml_property_animation(duration='control_.duration', loops=-1, running=True)
    marker = bpy.context.object
    marker.parent = parent
    assert marker['qml_type'] == 'Qml.PropertyAnimation'
    assert module.OBJECT_PT_qml_property_animation.poll(bpy.context)
    marker.qml_property_animation_easing_type = 'InOutElastic'
    assert marker['easing.type'] == 'InOutElastic'
    marker['easing.amplitude'] = 1.2
    marker['easing.period'] = 0.45
    marker['easing.overshoot'] = 1.7
    source = '\n'.join(module.export_qml_property_animation(marker, 'animation', 1, 'node_AnimatedMotor'))
    for token in ['target: parent', 'duration: control_.duration', 'from: Qt.vector3d(target.eulerRotation.x',
                  'to: Qt.vector3d(target.eulerRotation.x', 'loops: Animation.Infinite', 'running: true',
                  'easing.type: Easing.InOutElastic', 'easing.amplitude: 1.2']:
        assert token in source, token
    settings = SimpleNamespace(report=lambda *args: None, convert_coords=True, export_animations=False,
                               export_lights=False, export_cameras=False, apply_modifiers=False, generate_lods=False)
    marker['running'] = False
    assert addon.BalsamExporter(str(out / 'ElasticScene.qml'), settings).export() == {'FINISHED'}
    for easing in module.EASING_TYPES:
        marker['easing.type'] = easing
        assert 'easing.type: Easing.' + easing in '\n'.join(module.export_qml_property_animation(marker, 'animation', 1))
    marker['easing.type'] = 'BezierSpline'
    marker['easing.bezierCurve'] = '[0.25, 0.1, 0.25, 1, 1, 1]'
    marker['running'] = False
    marker['properties'] = 'eulerRotation'
    settings = SimpleNamespace(report=lambda *args: None, convert_coords=True, export_animations=False,
                               export_lights=False, export_cameras=False, apply_modifiers=False, generate_lods=False)
    exporter = addon.BalsamExporter(str(out / 'AnimationScene.qml'), settings)
    assert exporter.export() == {'FINISHED'}
    qml = (out / 'AnimationScene.qml').read_text()
    assert 'id: node_AnimatedMotor' in qml
    assert 'readonly property QtObject parent: node_AnimatedMotor' in qml
    assert 'easing.bezierCurve: [0.25, 0.1, 0.25, 1, 1, 1]' in qml
    assert 'properties: "eulerRotation"' in qml
    # An ordinary Empty parent is also named and targeted (not its scene parent).
    empty = bpy.data.objects.new('EmptyParent', None)
    bpy.context.collection.objects.link(empty)
    marker.parent = empty
    marker['duration'] = '2500'
    marker['loops'] = 1
    empty_export = addon.BalsamExporter(str(out / 'EmptyScene.qml'), settings)
    assert empty_export.export() == {'FINISHED'}
    empty_qml = (out / 'EmptyScene.qml').read_text()
    assert 'id: node_EmptyParent' in empty_qml
    assert 'readonly property QtObject parent: node_EmptyParent' in empty_qml
    assert 'duration: 2500' in empty_qml and 'loops: 1' in empty_qml
    # Reusable components must own their IDs; no reference to a scene outside them.
    collection = bpy.data.collections.new('AnimatedCollection')
    for obj in [empty, marker]:
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        collection.objects.link(obj)
    root_animation = bpy.data.objects.new('RootAnimation', None)
    root_animation['qml_type'] = 'Qml.PropertyAnimation'
    collection.objects.link(root_animation)
    instance = bpy.data.objects.new('AnimationInstance', None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = collection
    bpy.context.collection.objects.link(instance)
    component_export = addon.BalsamExporter(str(out / 'InstanceScene.qml'), settings)
    assert component_export.export() == {'FINISHED'}
    assert component_export.component_files
    component = (out / next(iter(component_export.component_files))).read_text()
    assert 'id: root' in component
    assert 'readonly property QtObject parent: node_EmptyParent' in component
    for path in [root / 'shipmate/qt_property_animation.py', root / 'shipmate/qt_shipmate.py', root / '__init__.py']:
        ast.parse(path.read_text())
    print('PROPERTY_ANIMATION_EXPORT_TESTS_OK')
finally:
    addon.unregister()
    assert not hasattr(bpy.types.Object, 'qml_property_animation_easing_type')
