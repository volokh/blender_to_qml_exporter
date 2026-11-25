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
    'collection_properties_export_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def properties(obj):
    def plain(value):
        if isinstance(value, addon.IDPropertyGroup):
            return {key: plain(item) for key, item in value.items()}
        if isinstance(value, addon.IDPropertyArray):
            return value.to_list()
        return value
    return {key: plain(value) for key, value in obj.items()}


settings = SimpleNamespace(
    report=lambda *_args: None, convert_coords=True, export_animations=False,
    export_lights=False, export_cameras=False, apply_modifiers=False,
    generate_lods=False, manual_lods=False,
)

with tempfile.TemporaryDirectory(prefix='blender-collection-properties-') as folder:
    output = Path(folder)
    collection = bpy.data.collections.new('DoorWithHandle')
    mesh = bpy.data.meshes.new('DoorGeometry')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    door = bpy.data.objects.new('Door', mesh)
    handle = bpy.data.objects.new('DoorHandle', None)
    handle['qml_type'] = 'Qml.Rheostat'
    handle.parent = door
    for obj in [door, handle]:
        collection.objects.link(obj)
        obj['closed'] = False
        obj['enabled'] = False
        obj['options'] = {'values': [7, 8], 'label': 'original'}
    nested = bpy.data.collections.new('NestedParts')
    child = bpy.data.objects.new('NestedMember', None)
    nested.objects.link(child)
    collection.children.link(nested)
    inner_collection = bpy.data.collections.new('InnerCollection')
    inner_member = bpy.data.objects.new('InnerMember', None)
    inner_member['closed'] = False
    inner_collection.objects.link(inner_member)
    inner_instance = bpy.data.objects.new('InnerInstance', None)
    inner_instance.instance_type = 'COLLECTION'
    inner_instance.instance_collection = inner_collection
    collection.objects.link(inner_instance)
    source = output / 'library.blend'
    bpy.data.libraries.write(str(source), {collection})
    for obj in [door, handle, child, inner_instance, inner_member]:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)
    bpy.data.collections.remove(nested)
    bpy.data.collections.remove(inner_collection)
    bpy.data.meshes.remove(mesh)
    with bpy.data.libraries.load(str(source), link=True) as (_, data):
        data.collections = ['DoorWithHandle']
    linked = data.collections[0]
    assert all(obj.library for obj in linked.all_objects)
    library_objects = [obj for obj in bpy.data.objects if obj.library]
    originals = {obj: properties(obj) for obj in library_objects}
    for name, value in [('ClosedInstance', True), ('OpenInstance', False), ('PlainInstance', None)]:
        instance = bpy.data.objects.new(name, None)
        instance.instance_type = 'COLLECTION'
        instance.instance_collection = linked
        if value is not None:
            instance['closed'] = value
            instance['options'] = {'values': [1, 2, 3], 'label': name}
            instance['newProperty'] = name
        bpy.context.scene.collection.objects.link(instance)
    bpy.context.view_layer.update()

    observations = []

    class InspectingExporter(addon.BalsamExporter):
        def _obj_qml(self, obj, *args, **kwargs):
            if obj.library:
                observations.append((obj.name, properties(obj)))
                if 'closed' in obj:
                    assert obj['closed'] == obj.get('closed')
            return super()._obj_qml(obj, *args, **kwargs)

    original_shipmate = addon.export_shipmate

    def export_shipmate(obj, *args, **kwargs):
        lines = original_shipmate(obj, *args, **kwargs)
        if obj.name == 'DoorHandle':
            lines.insert(-1, f'    property bool inheritedClosed: {str(bool(obj["closed"])).lower()}')
        return lines

    addon.export_shipmate = export_shipmate
    try:
        exporter = InspectingExporter(str(output / 'Scene.qml'), settings)
        assert exporter.export() == {'FINISHED'}
        assert {obj: properties(obj) for obj in library_objects} == originals
        assert len(observations) == 15, observations
        for label, closed in [('ClosedInstance', True), ('OpenInstance', False)]:
            members = [(name, props) for name, props in observations
                       if props.get('newProperty') == label]
            assert {name for name, _ in members} == {
                'Door', 'DoorHandle', 'NestedMember', 'InnerInstance', 'InnerMember',
            }
            for name, props in members:
                assert props['closed'] == closed, (name, props)
                assert props['options'] == {'values': [1, 2, 3], 'label': label}
        scene = (output / 'Scene.qml').read_text()
        types = re.findall(r'^\s*(DoorWithHandle\w*) \{', scene, re.MULTILINE)
        assert len(types) == len(set(types)) == 3, scene
        bodies = [(output / (name + '.qml')).read_text() for name in types]
        assert sum('inheritedClosed: true' in body for body in bodies) == 1
        assert sum('inheritedClosed: false' in body for body in bodies) == 2
        sources = [re.search(r'source: "([^"]+\.mesh)"', body).group(1) for body in bodies]
        assert len(set(sources)) == 3, sources
        qrc = (output / 'Scene.qrc').read_text()
        for name in types:
            assert name + '.qml' in qrc
        for mesh_source in sources:
            assert (output / mesh_source).is_file()
        before = {path.name: path.read_text() for path in output.glob('*.qml')}
        assert InspectingExporter(str(output / 'Scene.qml'), settings).export() == {'FINISHED'}
        assert before == {path.name: path.read_text() for path in output.glob('*.qml')}
    finally:
        addon.export_shipmate = original_shipmate

    class FailingExporter(addon.BalsamExporter):
        def process_collection(self, collection, *args, **kwargs):
            if collection.name == self.fail_on:
                assert all(obj['closed'] for obj in collection.all_objects)
                raise RuntimeError('Expected test failure')
            return super().process_collection(collection, *args, **kwargs)

    for collection_name in ['DoorWithHandle', 'InnerCollection']:
        failing = FailingExporter(str(output / 'Failure.qml'), settings)
        failing.fail_on = collection_name
        try:
            failing._obj_qml(bpy.data.objects['ClosedInstance'])
        except RuntimeError as error:
            assert str(error) == 'Expected test failure'
        else:
            raise AssertionError('Expected export failure')
        assert {obj: properties(obj) for obj in library_objects} == originals
        assert failing._instance_path == []
        assert failing._instance_property_suffix == ''

    instance = bpy.data.objects['ClosedInstance']
    instance['enabled'] = False
    instance['DoorHandle.enabled'] = True
    instance['DoorHandle.easing.type'] = 'OutQuad'
    instance['InnerMember.enabled'] = True
    instance['InnerInstance.onlyHere'] = 42
    instance['MissingObject.enabled'] = True
    messages = []
    settings.report = lambda levels, message: messages.append((levels, message))
    observations.clear()
    targeted = InspectingExporter(str(output / 'Targeted.qml'), settings)
    targeted._obj_qml(instance)
    assert len(observations) == 5, observations
    for name, props in observations:
        assert props['enabled'] == (name in {'DoorHandle', 'InnerMember'}), (name, props)
        assert ('onlyHere' in props) == (name == 'InnerInstance'), (name, props)
        assert ('easing.type' in props) == (name == 'DoorHandle'), (name, props)
        assert not any(key.startswith(('DoorHandle.', 'InnerMember.', 'MissingObject.'))
                       for key in props), (name, props)
    assert dict(observations)['DoorHandle']['easing.type'] == 'OutQuad'
    assert any('WARNING' in levels and 'MissingObject' in message
               for levels, message in messages), messages
    assert {obj: properties(obj) for obj in library_objects} == originals
    assert targeted._instance_target_properties == {}
    assert targeted._instance_property_sources == {}
    for collection_name in ['DoorWithHandle', 'InnerCollection']:
        failing = FailingExporter(str(output / 'TargetedFailure.qml'), settings)
        failing.fail_on = collection_name
        try:
            failing._obj_qml(instance)
        except RuntimeError as error:
            assert str(error) == 'Expected test failure'
        else:
            raise AssertionError('Expected export failure')
        assert {obj: properties(obj) for obj in library_objects} == originals
        assert failing._instance_target_properties == {}
        assert failing._instance_property_sources == {}

    plain_instance = bpy.data.objects['PlainInstance']
    plain_instance['DoorHandle.enabled'] = True
    observations.clear()
    targeted._obj_qml(plain_instance)
    for name, props in observations:
        if name == 'DoorHandle':
            assert props['enabled'] is True
        else:
            assert props == originals[bpy.data.objects[name]], (name, props)
    assert {obj: properties(obj) for obj in library_objects} == originals
    for invalid_key in ['.enabled', 'DoorHandle.']:
        plain_instance[invalid_key] = True
        try:
            targeted._obj_qml(plain_instance)
        except ValueError as error:
            assert 'invalid object-property override' in str(error)
        else:
            raise AssertionError('Expected invalid override failure')
        del plain_instance[invalid_key]
        assert targeted._instance_path == []
        assert targeted._instance_target_properties == {}
        assert {obj: properties(obj) for obj in library_objects} == originals

print('COLLECTION_PROPERTIES_EXPORT_TESTS_OK')
