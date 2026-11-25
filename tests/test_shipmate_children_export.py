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
