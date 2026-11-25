"""Run with Blender --background --factory-startup --python this_file.py."""
import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'shipmate_children_export_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def empty(name, parent=None, qml_type=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    if qml_type:
        obj['qml_type'] = qml_type
    return obj


parent = empty('ControlParent')
control = empty('NestedRheostat', parent, 'Qml.Rheostat')
hover = empty('HoverChild', control, 'Qml.HoverableMatSwitcher')
empty('HoverGrandchild', hover)
empty('ControlSibling', control)
hidden = empty('HiddenHover', control, 'Qml.HoverableMatSwitcher')
hidden.hide_render = True
empty('HiddenGrandchild', hidden)
empty('LeafRheostat', parent, 'Qml.Rheostat')
bpy.context.view_layer.update()

settings = SimpleNamespace(
    report=lambda *_args: None, convert_coords=True, export_animations=False,
    export_lights=False, export_cameras=False, apply_modifiers=False,
    generate_lods=False, manual_lods=False,
)
with tempfile.TemporaryDirectory(prefix='blender-shipmate-children-') as folder:
    exporter = addon.BalsamExporter(str(Path(folder) / 'Scene.qml'), settings)
    blocks = exporter._obj_qml(parent, d=0)
    text = '\n'.join(blocks)
    stack = []
    ancestors = {}
    for line in text.splitlines():
        opening = re.match(r'\s*([\w.]+)\s*\{', line)
        if opening:
            stack.append(opening.group(1))
        name = re.search(r"""objectName:\s*['"]([^'"]+)['"]""", line)
        if name:
            ancestors[name.group(1)] = list(stack)
        if line.strip() == '}':
            stack.pop()
    assert not stack, text
    assert ancestors['HoverGrandchild'] == [
        'Node', 'LM.RheostatButton', 'LM.HoverableMaterialSwitcher', 'Node',
    ], text
    assert ancestors['ControlSibling'] == ['Node', 'LM.RheostatButton', 'Node'], text
    assert text.count('LM.HoverableMaterialSwitcher {') == 1, text
    assert 'HiddenGrandchild' not in text, text
    assert text.count("objectName: 'LeafRheostat'") == 1, text
    for name in ['HoverGrandchild', 'ControlSibling']:
        assert text.count('objectName: "' + name + '"') == 1, text
    assert exporter.export() == {'FINISHED'}
    exported = '\n'.join(path.read_text() for path in Path(folder).glob('*.qml'))
    assert exported.count('LM.HoverableMaterialSwitcher {') == 1, exported
    assert 'import LogicModule as LM' in exported
    assert 'HoverGrandchild' in exported

print('SHIPMATE_CHILDREN_EXPORT_TESTS_OK')

# Exercise the same parent chain after it is linked from a separate .blend.
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
with tempfile.TemporaryDirectory(prefix='blender-linked-shipmate-children-') as folder:
    output = Path(folder)
    collection = bpy.data.collections.new('LinkedControls')
    mesh = bpy.data.meshes.new('ControlHousingMesh')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    housing = bpy.data.objects.new('Housing', mesh)
    rheostat = bpy.data.objects.new('Rheostat', None)
    rheostat['qml_type'] = 'Qml.Rheostat'
    rheostat.parent = housing
    hover = bpy.data.objects.new('HoverSwitcher', None)
    hover['qml_type'] = 'Qml.HoverableMatSwitcher'
    hover.parent = rheostat
    for obj in [housing, rheostat, hover]:
        collection.objects.link(obj)
    library = output / 'library.blend'
    bpy.data.libraries.write(str(library), {collection})
    for obj in [housing, rheostat, hover]:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)
    bpy.data.meshes.remove(mesh)
    with bpy.data.libraries.load(str(library), link=True) as (_, data):
        data.collections = ['LinkedControls']
    linked_collection = data.collections[0]
    instance = bpy.data.objects.new('LinkedControlsInstance', None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = linked_collection
    bpy.context.scene.collection.objects.link(instance)
    bpy.context.view_layer.update()

    exporter = addon.BalsamExporter(str(output / 'LinkedScene.qml'), settings)
    assert exporter.export() == {'FINISHED'}
    qml_files = list(output.glob('*.qml'))
    assert len(qml_files) >= 2, [path.name for path in qml_files]
    component = (output / 'LinkedControls.qml').read_text()
    assert component.index('LM.RheostatButton {') < component.index(
        'LM.HoverableMaterialSwitcher {'), component
    rheostat_block = component.split('LM.RheostatButton {', 1)[1].split(
        'LM.HoverableMaterialSwitcher {', 1)[0]
    assert 'LM.HoverableMaterialSwitcher' not in rheostat_block
    assert 'view: parent' in component

print('LINKED_SHIPMATE_CHILDREN_EXPORT_TESTS_OK')
