"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.py."""
import importlib.util
import sys
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'shipmate_export_context_test', root / '__init__.py',
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
shipmate = sys.modules[spec.name + '.shipmate.qt_shipmate']

obj = bpy.data.objects.new('ContextControl', None)
obj['change_grade'] = (1.0, 0.0, 0.0)
obj.location = (1, 2, 3)
contexts = [
    addon.ShipmateExportContext('control', 0, 'parentNode'),
    addon.ShipmateExportContext('control', 3, 'otherParent', False, False),
]
for qml_type, export in [
    ('Qml.Hatch', shipmate.export_qml_hatch),
    ('Qml.Rheostat', shipmate.export_qml_rheostat),
    ('Qml.AnimatedGauge', shipmate.export_qml_animated_gauge),
    ('Qml.HoverableMatSwitcher', shipmate.export_qml_hoverable_mat_switcher),
    ('Qml.NodeSwitcher', shipmate.export_qml_node_switcher),
    ('Qml.PropertyAnimation', shipmate.export_qml_property_animation),
]:
    obj['qml_type'] = qml_type
    for context in contexts:
        lines = export(obj, context)
        assert lines == addon.export_shipmate(obj, context), qml_type
        assert lines[0].startswith('    ' * context.depth + 'LM.'), lines
        if qml_type == 'Qml.PropertyAnimation':
            assert f'    target: {context.parent_id}' in '\n'.join(lines), lines
        if qml_type in {'Qml.Rheostat', 'Qml.AnimatedGauge'}:
            assert any('objectName:' in line for line in lines) == context.with_object_name, lines
        if qml_type in {'Qml.Hatch', 'Qml.AnimatedGauge'}:
            expected = '(1.0, 3.0, -2.0)' if context.convert_coords else '(1.0, 2.0, 3.0)'
            assert any(expected in line for line in lines), lines

try:
    shipmate.export_qml_property_animation(obj, addon.ShipmateExportContext('animation', 0))
except ValueError as error:
    assert 'parent_id must not be None' in str(error), error
else:
    raise AssertionError('Expected missing animation parent error')

print('SHIPMATE_EXPORT_CONTEXT_TESTS_OK')
