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
    'object_properties_export_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    return obj


def exported(exporter, obj):
    bpy.context.view_layer.update()
    return '\n'.join(exporter._obj_qml(obj, d=0))


messages = []
settings = SimpleNamespace(
    report=lambda levels, message: messages.append((levels, message)),
    convert_coords=True, export_animations=False, export_lights=True,
    export_cameras=True, apply_modifiers=False, generate_lods=False, manual_lods=False,
)

with tempfile.TemporaryDirectory(prefix='blender-object-properties-') as folder:
    output = Path(folder)
    exporter = addon.BalsamExporter(str(output / 'Scene.qml'), settings)
    node = empty('CustomNode')
    node['self.id'] = 'customNode'
    node['count'] = 3
    node['amount'] = 1.25
    node['active'] = True
    node['label'] = '"text"'
    node['binding'] = 'customNode.amount * 2'
    node['boundAmount'] = 1.0
    node['self.boundAmount'] = 'customNode.amount'
    node['options'] = {'label': 'literal', 'count': 2}
    node['values'] = [1, 2, 3]
    node['objectName'] = '"plainOverride"'
    node['self.objectName'] = '"explicitOverride"'
    node['self.position'] = 'Qt.vector3d(4, 5, 6)'
    node['booleans'] = {'internal': True}
    node['cycles'] = {'samples': 16}
    node['_RNA_UI'] = {'count': {'min': 0}}
    child = empty('CustomChild', node)
    child['self.id'] = 'customChild'
    child['self.objectName'] = '"childOverride"'
    child['count'] = 9
    text = exported(exporter, node)
    for expected in [
        'id: customNode', 'id: customChild',
        'property int count: 3', 'property real amount: 1.25',
        'property bool active: true', 'property var label: "text"',
        'property var binding: customNode.amount * 2',
        'property real boundAmount: customNode.amount',
        'property var options: ({"label": "literal", "count": 2})',
        'property var values: [1, 2, 3]',
        'objectName: "explicitOverride"', 'position: Qt.vector3d(4, 5, 6)',
        'objectName: "childOverride"', 'property int count: 9',
    ]:
        assert expected in text, (expected, text)
    assert 'plainOverride' not in text and 'CustomNode"' not in text, text
    assert 'self.' not in text and 'property var objectName' not in text, text
    assert 'booleans:' not in text and 'cycles:' not in text and '_RNA_UI' not in text, text
    assert exporter.node_ids[node.name] == 'customNode'
    assert addon.custom_qml_type(2 ** 40, node.name, 'wideInteger', settings.report) == 'var'
    assert any('outside QML int range' in message for _, message in messages), messages
    if '--' in sys.argv:
        fixtures = Path(sys.argv[sys.argv.index('--') + 1])
        fixtures.mkdir(parents=True, exist_ok=True)
        (fixtures / 'ObjectProperties.qml').write_text('import QtQuick\nimport QtQuick3D\n' + text)

    rheostat = empty('Control', node)
    rheostat['qml_type'] = 'Qml.Rheostat'
    rheostat['value'] = [1.0, 2.0, 3.0]
    rheostat['change_step'] = [10.0, 20.0, 30.0]
    rheostat['change_duration'] = 1500.0
    rheostat['step'] = 0.5
    rheostat['hover_text'] = 'Original hover text'
    rheostat['value_out'] = '{\n    const text = "}";\n    target.value = value;\n}'
    rheostat['self.id'] = 'myControl'
    rheostat['self.value'] = 'customNode.amount'
    rheostat['self.onValueChanged'] = '{ target.value = value * 2; }'
    rheostat['customValue'] = 2.5
    rheostat['minValue'] = 1.5
    text = exported(exporter, rheostat)
    assert 'id: myControl' in text and 'value: customNode.amount' in text, text
    assert len(re.findall(r'^\s*value:', text, re.MULTILINE)) == 1, text
    assert 'minValue: 1.5' in text and 'maxValue: 3.0' in text, text
    assert len(re.findall(r'^\s*minValue:', text, re.MULTILINE)) == 1, text
    assert 'changeStep: Qt.vector3d(10.0, 30.0, -20.0)' in text, text
    assert 'changeDuration: 1500.0' in text and 'step: 0.5' in text, text
    assert 'picker.hoverText: `Original hover text`' in text, text
    assert 'onValueChanged: { target.value = value * 2; }' in text, text
    assert 'const text' not in text and 'target.value = value;' not in text, text
    assert 'property real customValue: 2.5' in text, text
    for key in ['qml_type', 'change_step', 'value_out', 'hover_text', 'value', 'step']:
        assert not re.search(r'property \w+ ' + key + r'\s*:', text), text

    animation = empty('Animation', node)
    animation['qml_type'] = 'Qml.PropertyAnimation'
    animation['property'] = 'eulerRotation'
    animation['properties'] = ''
    animation['loops'] = -1
    animation['easing.type'] = 'InOutQuad'
    text = exported(exporter, node)
    assert 'target: customNode' in text, text
    assert 'property: "eulerRotation"' in text, text
    assert 'loops: Animation.Infinite' in text, text
    assert 'easing.type: Easing.InOutQuad' in text, text
    assert 'property var qml_type' not in text, text

    controls = [
        ('Qml.Hatch', {
            'final_rotation': [10.0, 20.0, 30.0], 'final_position': [1.0, 2.0, 3.0],
            'hover_text': 'Hatch text', 'value_out': 'console.log(isFinal)',
            'validator': 'null', 'stepPositiveSound': 'qrc:/open.wav',
            'stepNegativeSound': 'qrc:/close.wav',
        }),
        ('Qml.Rheostat', {
            'value': [1.0, 2.0, 3.0], 'step': 0.5, 'change_step': [10.0, 0.0, 0.0],
            'change_duration': 100.0, 'initial_value': 1.0, 'hover_text': 'Control text',
            'value_out': 'console.log(value)', 'blocker_visible': 'true',
            'blocker_text': '"Locked"', 'validator': 'null', 'sequentialMode': True,
            'stepPositiveSound': 'qrc:/up.wav', 'stepNegativeSound': 'qrc:/down.wav',
        }),
        ('Qml.AnimatedGauge', {
            'value': [1.0, 2.0, 3.0], 'change_grade': [10.0, 0.0, 0.0],
            'change_step': [1.0, 0.0, 0.0], 'grade': 1.0, 'change_duration': 100.0,
            'initial_value': 1.0, 'rotate': True, 'hover_text': 'Gauge text',
            'value_in': 'customNode.amount',
        }),
        ('Qml.HoverableMatSwitcher', {}),
        ('Qml.PropertyAnimation', {
            'property': 'eulerRotation', 'properties': '', 'duration': '2500',
            'from': '0', 'to': '360', 'easing.type': 'InOutQuad',
            'easing.amplitude': 1.0, 'easing.overshoot': 1.7, 'easing.period': 0.45,
            'easing.bezierCurve': '', 'loops': -1, 'running': 'false',
        }),
    ]
    for qml_type, values in controls:
        control = empty('Unchanged' + qml_type.split('.')[-1], node)
        control['qml_type'] = qml_type
        for key, value in values.items():
            control[key] = value
        baseline = addon.export_shipmate(control, 'control', 0, 'customNode')
        assert exporter._apply_object_custom_properties(control, baseline) == baseline, qml_type

    mesh = bpy.data.meshes.new('CustomMeshData')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    model = bpy.data.objects.new('CustomModel', mesh)
    bpy.context.scene.collection.objects.link(model)
    model['self.id'] = 'customModel'
    model['self.source'] = '"#Sphere"'
    model['quantity'] = 4
    model_animation = empty('ModelAnimation', model)
    model_animation['qml_type'] = 'Qml.PropertyAnimation'
    text = exported(exporter, model)
    assert 'id: customModel' in text and 'source: "#Sphere"' in text, text
    assert 'property int quantity: 4' in text, text
    assert len(re.findall(r'^\s*source:', text, re.MULTILINE)) == 1, text
    assert text.count('id: customModel') == 1 and 'target: customModel' in text, text
    bpy.context.view_layer.objects.active = model
    model.select_set(True)
    bpy.ops.rigidbody.object_add()
    text = exported(exporter, model)
    assert text.index('DynamicRigidBody {') < text.index('Model {') < text.index('id: customModel'), text
    assert len(re.findall(r'^\s*id: customModel$', text, re.MULTILINE)) == 1, text

    for kind, data in [
        ('Camera', bpy.data.cameras.new('CustomCameraData')),
        ('Light', bpy.data.lights.new('CustomLightData', 'POINT')),
        ('Speaker', bpy.data.speakers.new('CustomSpeakerData')),
    ]:
        obj = bpy.data.objects.new('Custom' + kind, data)
        bpy.context.scene.collection.objects.link(obj)
        obj['self.id'] = 'custom' + kind
        obj['quantity'] = 2
        text = exported(exporter, obj)
        assert 'id: custom' + kind in text, text
        assert 'property int quantity: 2' in text, text

    collection = bpy.data.collections.new('CustomCollection')
    member = bpy.data.objects.new('LibraryMember', None)
    member['self.id'] = 'libraryMember'
    member['amount'] = 7.0
    collection.objects.link(member)
    instance = empty('CollectionInstance')
    instance.instance_type = 'COLLECTION'
    instance.instance_collection = collection
    instance['self.id'] = 'collectionInstance'
    instance['self.objectName'] = '"instanceOverride"'
    instance['amount'] = 4.0
    text = exported(exporter, instance)
    component = (output / 'CustomCollection.qml').read_text()
    assert 'id: collectionInstance' in text, text
    assert 'objectName: "instanceOverride"' in text, text
    assert 'amount: 4.0' in text, text
    assert 'id: libraryMember' in component, component
    assert 'property real amount: 7.0' in component, component
    assert re.search(r'^    property real amount$', component, re.MULTILINE), component
    assert 'override_self' not in text + component, text + component
    assert member['amount'] == 7.0 and member['self.id'] == 'libraryMember'
    assert not exporter._object_property_sources

    synthetic = empty('Synthetic')
    synthetic['existing'] = 2.5
    synthetic['self.handler'] = '{ doSomething(); }'
    lines = [
        'Node {', '    property int existing: 1',
        '    existing: 10',
        '    handler: {\n        const quoted = "}}";\n'
        '        // }}}\n        if (/}/.test(quoted)) { oldCall(); }\n    }',
        '    Node {', '        property int existing: 99', '    }', '}',
    ]
    text = '\n'.join(exporter._apply_object_custom_properties(synthetic, lines))
    assert 'property real existing: 2.5' in text, text
    assert 'property int existing: 99' in text, text
    assert 'existing: 10' not in text and 'oldCall' not in text, text
    assert 'handler: { doSomething(); }' in text, text

    invalid = empty('Invalid')
    for key, value in [
        ('self.id', 'InvalidId'), ('self.id', 'not an id'), ('self.id', '"quoted"'),
        ('self.id', 'for'), ('self.id', 4), ('self.', True), ('bad-name', True),
        ('default', True), ('id', 'useSelfId'),
        ('blank', ' '), ('nonfinite', float('nan')),
    ]:
        invalid[key] = value
        try:
            exported(exporter, invalid)
        except ValueError as error:
            assert invalid.name in str(error), error
        else:
            raise AssertionError(f'Expected invalid property failure: {key}: {value!r}')
        del invalid[key]
    invalid.hide_render = True
    assert exporter.export() == {'FINISHED'}

print('OBJECT_PROPERTIES_EXPORT_TESTS_OK')
