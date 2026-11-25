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
    handle['pressure'] = 7.0
    handle.parent = door
    for obj in [door, handle]:
        collection.objects.link(obj)
        obj['closed'] = False
        obj['enabled'] = False
        obj['options'] = {'values': [7, 8], 'label': 'original'}
        obj['booleans'] = {'libraryOnly': True, 'nested': {'oldFlag': False}}
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
    inner_instance['localSetting'] = 7
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
            instance['booleans'] = {'enabled': True, 'flags': [True, False]}
            instance['cycles'] = {'samples': 16}
            instance['newProperty'] = name
            instance['pressure'] = 1.5 if value else 2
            instance['count'] = 3
            instance['mixed'] = True if value else 'disabled'
            instance['vectorData'] = [1.0, 2.0, 3.0]
        bpy.context.scene.collection.objects.link(instance)
    bpy.context.view_layer.update()

    observations = []
    messages = []
    settings.report = lambda levels, message: messages.append((levels, message))

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
            lines.insert(-1, f'    closed: {str(bool(obj["closed"])).lower()}')
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
                if name in {'Door', 'DoorHandle'}:
                    assert props['booleans'] == {
                        'libraryOnly': True, 'nested': {'oldFlag': False}}
                else:
                    assert 'booleans' not in props
                assert 'cycles' not in props
        scene = (output / 'Scene.qml').read_text()
        types = re.findall(r'^\s*(DoorWithHandle\w*) \{', scene, re.MULTILINE)
        assert len(types) == 3 and set(types) == {'DoorWithHandle'}, scene
        bodies = [(output / 'DoorWithHandle.qml').read_text()]
        assert 'closed: root.closed' not in bodies[0]
        assert 'localSetting: 7' in bodies[0]
        assert 'newProperty:' not in bodies[0]
        assert 'property real pressure: 7.0' in bodies[0]
        assert 'property real pressure: 1.5' not in bodies[0]
        assert sum('property bool closed' in body for body in bodies) == 1
        assert 'property real pressure' in bodies[0]
        assert 'property int count' in bodies[0]
        assert 'property var newProperty' in bodies[0]
        assert 'property var mixed' in bodies[0]
        assert 'property var vectorData' in bodies[0]
        assert any('WARNING' in levels and 'incompatible override types' in message
                   and 'mixed' in message for levels, message in messages), messages
        assert 'property var booleans' not in bodies[0]
        assert 'property var cycles' not in bodies[0]
        assert 'property var options' in bodies[0]
        assert not list(output.glob('*_Props_*.qml'))
        assert 'closed: true' in scene
        assert 'closed: false' in scene
        assert 'newProperty: ClosedInstance' in scene
        assert 'newProperty: OpenInstance' in scene
        assert 'booleans:' not in scene
        assert 'cycles:' not in scene
        sources = [re.search(r'source: "([^"]+\.mesh)"', body).group(1) for body in bodies]
        assert len(set(sources)) == 1, sources
        qrc = (output / 'Scene.qrc').read_text()
        for name in types:
            assert name + '.qml' in qrc
        for mesh_source in sources:
            assert (output / mesh_source).is_file()
        before = {path.name: path.read_text() for path in output.glob('*.qml')}
        assert InspectingExporter(str(output / 'Scene.qml'), settings).export() == {'FINISHED'}
        after = {path.name: path.read_text() for path in output.glob('*.qml')}
        assert before == after, {
            name: (before.get(name), after.get(name))
            for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)
        }
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

    instance = bpy.data.objects['ClosedInstance']
    instance['enabled'] = False
    instance['DoorHandle.enabled'] = True
    instance['DoorHandle.easing.type'] = 'OutQuad'
    instance['InnerMember.enabled'] = True
    instance['InnerInstance.onlyHere'] = 42
    instance['MissingObject.enabled'] = True
    instance['DoorHandle.pressure'] = 1.25
    messages = []
    settings.report = lambda levels, message: messages.append((levels, message))
    observations.clear()
    targeted = InspectingExporter(str(output / 'Targeted.qml'), settings)
    assert targeted.export() == {'FINISHED'}
    targeted_members = [(name, props) for name, props in observations
                        if props.get('newProperty') == 'ClosedInstance']
    assert len(targeted_members) == 5, targeted_members
    for name, props in targeted_members:
        assert props['enabled'] == (name in {'DoorHandle', 'InnerMember'}), (name, props)
        assert ('onlyHere' in props) == (name == 'InnerInstance'), (name, props)
        assert ('easing.type' in props) == (name == 'DoorHandle'), (name, props)
        assert not any(key.startswith(('DoorHandle.', 'InnerMember.', 'MissingObject.'))
                       for key in props), (name, props)
    assert dict(targeted_members)['DoorHandle']['easing.type'] == 'OutQuad'
    assert any('WARNING' in levels and 'MissingObject' in message
               for levels, message in messages), messages
    target_scene = (output / 'Targeted.qml').read_text()
    assert 'override_DoorHandle_enabled: true' in target_scene
    target_types = re.findall(r'^\s*(DoorWithHandle\w*) \{',
                              target_scene, re.MULTILINE)
    target_component = (output / 'DoorWithHandle.qml').read_text()
    assert 'enabled: root.override_DoorHandle_enabled' not in target_component
    assert 'property real override_DoorHandle_pressure' in target_component
    assert 'override_DoorHandle_pressure: 1.25' in target_scene
    assert 'root.override_InnerMember_enabled' not in target_component
    inner_types = re.findall(r'^\s*(InnerCollection\w*) \{',
                             target_component, re.MULTILINE)
    assert inner_types
    inner_component = (output / f'{inner_types[0]}.qml').read_text()
    assert 'enabled: root.override_InnerMember_enabled' not in inner_component
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
        elif name == 'InnerMember':
            assert props == {**originals[bpy.data.objects[name]], 'localSetting': 7}
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
        assert targeted._instance_target_properties == {}
        assert {obj: properties(obj) for obj in library_objects} == originals

    class GuardedMember:
        """Emulate Blender groups that reject assignment without recreation."""
        instance_type = 'NONE'

        def __init__(self, obj):
            self.obj = obj
            self.name = obj.name
            self.fail_next = False

        def __contains__(self, key):
            return key in self.obj

        def items(self):
            return self.obj.items()

        def __getitem__(self, key):
            return self.obj[key]

        def __delitem__(self, key):
            del self.obj[key]

        def __setitem__(self, key, value):
            if key in self.obj and isinstance(self.obj[key], addon.IDPropertyGroup):
                raise TypeError("Cannot assign dict to existing Group IDProperty")
            if self.fail_next:
                self.fail_next = False
                raise TypeError('Expected assignment failure')
            self.obj[key] = value

    guarded = GuardedMember(linked.objects['Door'])

    class GuardedInstance:
        name = name_full = 'GuardedInstance'
        library = None
        instance_collection = SimpleNamespace(all_objects=[guarded])

        def items(self):
            return [('options', {'enabled': True})]

    proxy = GuardedInstance()
    exporter = addon.BalsamExporter(str(output / 'Guarded.qml'), settings)
    for fail_assignment, fail_export in [(False, False), (False, True), (True, False)]:
        guarded.fail_next = fail_assignment
        try:
            with exporter._collection_instance_properties(proxy):
                assert guarded['options'].to_dict() == {'enabled': True}
                if fail_export:
                    raise RuntimeError('Expected guarded export failure')
        except (TypeError, RuntimeError) as error:
            assert str(error) == (
                'Expected assignment failure' if fail_assignment
                else 'Expected guarded export failure')
        else:
            assert not fail_assignment and not fail_export
        assert {obj: properties(obj) for obj in library_objects} == originals
        assert exporter._instance_target_properties == {}
        assert exporter._instance_property_sources == {}

    plain_instance['pressure'] = 'root.prop_value'
    plain_instance['literalText'] = '"value"'
    plain_instance['singleQuoted'] = "'va'"
    plain_instance['unquoted'] = 'val'
    plain_instance['DoorHandle.pressure'] = 'root.target_value'
    plain_instance['_qt_balsam_qml_expressions'] = {'pressure': 'real'}
    expression_exporter = addon.BalsamExporter(str(output / 'Expressions.qml'), settings)
    assert expression_exporter.export() == {'FINISHED'}
    text = (output / 'Expressions.qml').read_text()
    component = (output / 'DoorWithHandle.qml').read_text()
    assert 'pressure: root.prop_value' in text, text
    assert 'override_DoorHandle_pressure: root.target_value' in text, text
    assert 'literalText: "value"' in text, text
    assert "singleQuoted: 'va'" in text, text
    assert 'unquoted: val' in text, text
    assert 'property var pressure' in component, component
    assert 'property var override_DoorHandle_pressure' in component, component
    assert 'property var literalText' in component, component
    assert '_qt_balsam_qml_expressions' not in text and '_qt_balsam_qml_expressions' not in component
    assert {obj: properties(obj) for obj in library_objects} == originals
    plain_instance['DoorHandle.pressure'] = '   '
    try:
        addon.BalsamExporter(str(output / 'Invalid.qml'), settings).export()
    except ValueError as error:
        assert 'cannot be empty' in str(error)
    else:
        raise AssertionError('Expected empty QML expression failure')
    assert {obj: properties(obj) for obj in library_objects} == originals

print('COLLECTION_PROPERTIES_EXPORT_TESTS_OK')
