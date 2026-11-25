"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.py."""
import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'node_switcher_export_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
module = sys.modules[spec.name + '.shipmate.qt_node_switcher']

settings = SimpleNamespace(
    report=lambda *_args: None, convert_coords=True, export_animations=False,
    export_lights=False, export_cameras=False, apply_modifiers=False,
    generate_lods=False, manual_lods=False,
)

addon.register()
try:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    parent = bpy.data.objects.new('Control', None)
    parent['qml_type'] = 'Qml.Rheostat'
    bpy.context.scene.collection.objects.link(parent)
    bpy.ops.object.add_qml_node_switcher()
    switcher = bpy.context.object
    switcher.parent = parent
    assert switcher['qml_type'] == 'Qml.NodeSwitcher'
    assert module.OBJECT_PT_qml_node_switcher.poll(bpy.context)
    switcher['self.id'] = 'switcher'
    switcher['self.activated'] = 'root.enabled'
    switcher['count'] = 3
    child = bpy.data.objects.new('NestedChild', None)
    child.parent = switcher
    bpy.context.scene.collection.objects.link(child)
    hidden = bpy.data.objects.new('HiddenSwitcher', None)
    hidden['qml_type'] = 'Qml.NodeSwitcher'
    hidden.parent = switcher
    hidden.hide_render = True
    bpy.context.scene.collection.objects.link(hidden)
    bpy.context.view_layer.update()

    with tempfile.TemporaryDirectory(prefix='blender-node-switcher-') as folder:
        output = Path(folder)
        exporter = addon.BalsamExporter(str(output / 'Scene.qml'), settings)
        text = '\n'.join(exporter._obj_qml(parent, d=0))
        assert text.index('LM.RheostatButton {') < text.index('LM.NodeSwitcher {'), text
        assert text.index('LM.NodeSwitcher {') < text.index('objectName: "NestedChild"'), text
        assert text.count('LM.NodeSwitcher {') == 1, text
        assert 'id: switcher' in text and 'activated: root.enabled' in text, text
        assert 'property int count: 3' in text and 'view: parent' in text, text
        assert 'qml_type:' not in text, text
        switcher['self.view'] = 'root'
        text = '\n'.join(exporter._obj_qml(switcher, d=0))
        assert re.findall(r'^\s*view: (.+)$', text, re.MULTILINE) == ['root'], text
        for spelling in ['Qml.NodeSwitcher']:
            switcher['qml_type'] = spelling
            assert module.is_qml_node_switcher(switcher)
            assert 'LM.NodeSwitcher {' in '\n'.join(exporter._obj_qml(switcher, d=0))
        switcher['qml_type'] = 'Unrelated'
        assert not module.is_qml_node_switcher(switcher)
        switcher['qml_type'] = 'Qml.NodeSwitcher'
        assert exporter.export() == {'FINISHED'}
        scene = (output / 'Scene.qml').read_text()
        assert 'import LogicModule as LM' in scene and 'LM.NodeSwitcher {' in scene, scene

        collection = bpy.data.collections.new('LinkedSwitchers')
        for obj in [parent, switcher, child, hidden]:
            for old_collection in list(obj.users_collection):
                old_collection.objects.unlink(obj)
            collection.objects.link(obj)
        source = output / 'library.blend'
        bpy.data.libraries.write(str(source), {collection})
        for obj in [child, hidden, switcher, parent]:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
        with bpy.data.libraries.load(str(source), link=True) as (_, data):
            data.collections = ['LinkedSwitchers']
        instance = bpy.data.objects.new('LinkedInstance', None)
        instance.instance_type = 'COLLECTION'
        instance.instance_collection = data.collections[0]
        bpy.context.scene.collection.objects.link(instance)
        bpy.context.view_layer.update()
        assert addon.BalsamExporter(str(output / 'Linked.qml'), settings).export() == {'FINISHED'}
        component = (output / 'LinkedSwitchers.qml').read_text()
        assert 'import LogicModule as LM' in component, component
        assert component.index('LM.RheostatButton {') < component.index('LM.NodeSwitcher {'), component
        assert component.count('LM.NodeSwitcher {') == 1, component
        assert 'view: root' in component and 'activated: root.enabled' in component, component
        assert 'objectName: "NestedChild"' in component, component
finally:
    addon.unregister()
    assert not hasattr(bpy.types, 'OBJECT_OT_add_qml_node_switcher')
    assert not hasattr(bpy.types, 'OBJECT_PT_qml_node_switcher')

print('NODE_SWITCHER_EXPORT_TESTS_OK')
