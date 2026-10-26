"""Blender integration coverage for the default-on objectName export flag."""
import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[sys.argv.index('--') + 1])
spec = importlib.util.spec_from_file_location('object_name_export_test', root / '__init__.py', submodule_search_locations=[str(root)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    assert bpy.ops.export_scene.qt_balsam.get_rna_type().properties['with_object_name'].default is True
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for name, material_type in [('Plain', 'default'), ('Principled', 'principled'), ('Transparent', 'transparent')]:
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.name = name
        if name == 'Plain':
            obj['neverMirror'] = True
            obj.scale.x = -1
        mat = bpy.data.materials.new(name + 'Material')
        if material_type != 'default':
            mat.use_nodes = True
            if material_type == 'transparent':
                mat.node_tree.nodes.clear()
                mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
        obj.data.materials.append(mat)
    empty = bpy.data.objects.new('NamedEmpty', None)
    bpy.context.collection.objects.link(empty)
    camera = bpy.data.objects.new('NamedCamera', bpy.data.cameras.new('CameraData'))
    bpy.context.collection.objects.link(camera)
    light = bpy.data.objects.new('NamedLight', bpy.data.lights.new('LightData', 'POINT'))
    bpy.context.collection.objects.link(light)
    speaker = bpy.data.objects.new('NamedSpeaker', bpy.data.speakers.new('SpeakerData'))
    bpy.context.collection.objects.link(speaker)
    bpy.ops.object.add_qml_rheostat()
    bpy.context.object.name = 'NamedRheostat'
    bpy.ops.object.add_qml_animated_gauge()
    bpy.context.object.name = 'NamedGauge'
    collection = bpy.data.collections.new('NamedCollection')
    child = bpy.data.objects.new('ComponentChild', None)
    collection.objects.link(child)
    instance = bpy.data.objects.new('NamedInstance', None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = collection
    bpy.context.collection.objects.link(instance)
    bpy.context.view_layer.update()
    settings = SimpleNamespace(report=lambda *args: None, convert_coords=True, export_animations=False,
                               export_lights=True, export_cameras=True, apply_modifiers=False, generate_lods=False)
    assignment = re.compile(r'^\s*objectName\s*:', re.MULTILINE)
    exported = {}
    for label, flag in [('default', None), ('disabled', False), ('enabled', True)]:
        folder = out / label
        if flag is None:
            exporter = addon.BalsamExporter(str(folder / 'Scene.qml'), settings)
        else:
            settings.with_object_name = flag
            exporter = addon.BalsamExporter(str(folder / 'Scene.qml'), settings)
        assert exporter.export() == {'FINISHED'}
        files = {p.name: p.read_text() for p in folder.glob('*.qml')}
        exported[label] = files
        assert len(files) > 1, files.keys()
        assert any(assignment.search(text) for text in files.values()) == (flag is not False)
        if flag is False:
            for name, text in files.items():
                assert not assignment.search(text), name
        else:
            for name in ['NamedEmpty', 'NamedCamera', 'NamedLight', 'NamedSpeaker', 'NamedRheostat', 'NamedGauge', 'NamedInstance', 'PlainMaterial']:
                assert name in files['Scene.qml'], name
            assert assignment.search(files['Namedcollection.qml'])
    # Disabling names removes declarations only; the generated scene otherwise matches.
    for name, text in exported['enabled'].items():
        no_names = '\n'.join(line for line in text.splitlines() if not assignment.match(line))
        disabled = '\n'.join(line for line in exported['disabled'][name].splitlines() if line.strip())
        assert '\n'.join(line for line in no_names.splitlines() if line.strip()) == disabled, name
    # Explicit keyword override and the public Blender operator entry point.
    settings.with_object_name = True
    override = addon.BalsamExporter(str(out / 'override/Scene.qml'), settings, with_object_name=False)
    assert override.export() == {'FINISHED'}
    assert not assignment.search((out / 'override/Scene.qml').read_text())
    operator_path = out / 'operator/Scene.qml'
    operator_path.parent.mkdir(parents=True, exist_ok=True)
    assert bpy.ops.export_scene.qt_balsam(filepath=str(operator_path), with_object_name=False, apply_modifiers=False) == {'FINISHED'}
    assert not assignment.search(operator_path.read_text())
    for name in ['__init__.py', 'qt_bsdf_mat_importer.py', 'shipmate/qt_shipmate.py',
                 'shipmate/qt_step_sound.py', 'shipmate/qt_rheostat.py', 'shipmate/qt_animated_gauge.py']:
        ast.parse((root / name).read_text())
    print('OBJECT_NAME_EXPORT_TESTS_OK')
finally:
    addon.unregister()
