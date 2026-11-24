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
    "collection_name_export_test", root / "__init__.py",
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

collections = []
for name in ['TraficLights', 'Trafic Lights', 'HTTPServer', '123 Lights']:
    collection = bpy.data.collections.new(name)
    child = bpy.data.objects.new(name + 'Child', None)
    collection.objects.link(child)
    collections.append(collection)
    instance = bpy.data.objects.new(name + 'Instance', None)
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = collection
    bpy.context.scene.collection.objects.link(instance)

# The same collection can be exported through ordinary scene traversal as well.
bpy.context.scene.collection.children.link(collections[0])
bpy.context.view_layer.update()

settings = SimpleNamespace(
    report=lambda *_args: None, convert_coords=True, export_animations=False,
    export_lights=False, export_cameras=False, apply_modifiers=False,
    generate_lods=False,
)
with tempfile.TemporaryDirectory(prefix='blender-collection-names-') as folder:
    output = Path(folder)
    exporter = addon.BalsamExporter(str(output / 'Scene.qml'), settings)
    assert exporter.export() == {'FINISHED'}
    files = {path.name: path.read_text() for path in output.glob('*.qml')}
    assert 'TraficLights.qml' in files, files.keys()
    assert 'Traficlights.qml' not in files, files.keys()
    assert 'HTTPServer.qml' in files, files.keys()
    assert 'Col123Lights.qml' in files, files.keys()
    types = [exporter._collection_component_type(collection) for collection in collections]
    assert len(set(types)) == len(collections), types
    for collection, type_name in zip(collections, types):
        assert re.search(r'\b' + re.escape(type_name) + r'\s*\{', files['Scene.qml']), type_name
        assert collection.name + 'Child' in files[type_name + '.qml'], type_name
    qrc = (output / 'Scene.qrc').read_text()
    for type_name in types:
        assert type_name + '.qml' in qrc, type_name
    before = files
    assert addon.BalsamExporter(str(output / 'Scene.qml'), settings).export() == {'FINISHED'}
    assert before == {path.name: path.read_text() for path in output.glob('*.qml')}

print('COLLECTION_NAME_EXPORT_TESTS_OK')
