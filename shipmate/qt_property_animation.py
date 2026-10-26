"""Blender marker, editing panel and QML exporter for LM.PropertyAnimation."""
import json

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel

EASING_TYPES = ('Linear',) + tuple(
    direction + curve
    for curve in ('Quad', 'Cubic', 'Quart', 'Quint', 'Sine', 'Expo', 'Circ', 'Elastic', 'Back', 'Bounce')
    for direction in ('In', 'Out', 'InOut', 'OutIn')
) + ('InCurve', 'OutCurve', 'SineCurve', 'CosineCurve', 'BezierSpline')
EASING_ITEMS = tuple((name, name, 'Easing.' + name) for name in EASING_TYPES)
DEFAULTS = {
    'qml_type': 'Qml.PropertyAnimation',
    'property': 'eulerRotation',
    'properties': '',
    'duration': '2500',
    'from': 'Qt.vector3d(target.eulerRotation.x, target.eulerRotation.y, 0)',
    'to': 'Qt.vector3d(target.eulerRotation.x, target.eulerRotation.y, 360.)',
    'easing.type': 'Linear',
    'easing.amplitude': 1.0,
    'easing.overshoot': 1.70158,
    'easing.period': 0.45,
    'easing.bezierCurve': '',
    'loops': 1,
    'running': 'false',
}


class OBJECT_OT_add_qml_property_animation(Operator):
    bl_idname = 'object.add_qml_property_animation'
    bl_label = 'Qml.PropertyAnimation'
    bl_description = 'Add a parent-targeted LM.PropertyAnimation marker'
    bl_options = {'REGISTER', 'UNDO'}

    animation_property: StringProperty(name='Property', default=DEFAULTS['property'])
    properties: StringProperty(name='Properties', description='Optional comma-separated property names')
    duration: StringProperty(name='Duration (QML)', default=DEFAULTS['duration'])
    from_value: StringProperty(name='From (QML)', default=DEFAULTS['from'])
    to_value: StringProperty(name='To (QML)', default=DEFAULTS['to'])
    easing_type: EnumProperty(name='Easing type', items=EASING_ITEMS, default='Linear')
    easing_amplitude: FloatProperty(name='Amplitude', default=1.0)
    easing_overshoot: FloatProperty(name='Overshoot', default=1.70158)
    easing_period: FloatProperty(name='Period', default=0.45)
    easing_bezier_curve: StringProperty(name='Bezier curve (QML)', description='QML list of real values, e.g. [0.25, 0.1, 0.25, 1, 1, 1]')
    loops: IntProperty(name='Loops', default=1, min=-1, description='-1 means Animation.Infinite')
    running: StringProperty(name='Running', default=DEFAULTS['running'])

    def execute(self, context):
        obj = bpy.data.objects.new('Qml.PropertyAnimation', None)
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.25
        context.collection.objects.link(obj)
        obj.location = context.scene.cursor.location
        values = dict(DEFAULTS, **{
            'property': self.animation_property, 'properties': self.properties,
            'duration': self.duration, 'from': self.from_value, 'to': self.to_value,
            'easing.type': self.easing_type, 'easing.amplitude': self.easing_amplitude,
            'easing.overshoot': self.easing_overshoot, 'easing.period': self.easing_period,
            'easing.bezierCurve': self.easing_bezier_curve,
            'loops': self.loops, 'running': self.running,
        })
        for key, value in values.items():
            obj[key] = value
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


def is_qml_property_animation(obj):
    return obj.type == 'EMPTY' and obj.get('qml_type', '') == 'Qml.PropertyAnimation'


def get_easing_type(obj):
    value = str(obj.get('easing.type', 'Linear')).removeprefix('Easing.')
    return EASING_TYPES.index(value) if value in EASING_TYPES else 0


def set_easing_type(obj, value):
    obj['easing.type'] = EASING_TYPES[value]


class OBJECT_PT_qml_property_animation(Panel):
    bl_label = 'QML Property Animation'
    bl_idname = 'OBJECT_PT_qml_property_animation'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    @classmethod
    def poll(cls, context):
        return context.object is not None and is_qml_property_animation(context.object)

    def draw(self, context):
        layout = self.layout
        obj = context.object
        layout.label(text='Target: Blender parent (fixed)')
        if obj.parent is None:
            layout.label(text='Parent this marker to the object to animate.', icon='INFO')
        for key, label in [('property', 'Property'), ('properties', 'Properties'),
                           ('duration', 'Duration'), ('from', 'From'), ('to', 'To')]:
            if key in obj:
                layout.prop(obj, '["' + key + '"]', text=label)
        layout.prop(obj, 'qml_property_animation_easing_type', text='Easing type')
        for key, label in [('easing.amplitude', 'Amplitude'), ('easing.overshoot', 'Overshoot'),
                           ('easing.period', 'Period'), ('easing.bezierCurve', 'Bezier curve'),
                           ('loops', 'Loops (-1 = infinite)'), ('running', 'Running')]:
            if key in obj:
                layout.prop(obj, '["' + key + '"]', text=label)


def export_qml_property_animation(obj, nid, depth, parent_id):
    """Expression strings are QML code; only property-name strings are quoted."""

    if parent_id is None:
        raise ValueError(f"Cannot export animation {nid!r}: parent_id must not be None")

    indent = '    ' * depth
    child = indent + '    '
    lines = [indent + 'LM.PropertyAnimation {',
             #f'{child}id: {nid}',
             # Animation has no built-in parent property. Supply its actual Blender parent.
             #f'{child}readonly property QtObject parent: ' + target_id,
             f'{child}target: {parent_id}']
    for name in ('property', 'properties'):
        value = str(obj.get(name, DEFAULTS[name]))
        if value:
            lines.append(child + name + ': ' + json.dumps(value))
    for name in ('duration', 'from', 'to'):
        value = str(obj.get(name, DEFAULTS[name]))
        if value.strip():
            lines.append(child + name + ': ' + value)
    easing = str(obj.get('easing.type', 'Linear'))
    lines.append(child + 'easing.type: ' + (easing if easing.startswith('Easing.') else 'Easing.' + easing))
    for name in ('easing.amplitude', 'easing.overshoot', 'easing.period'):
        lines.append(child + name + ': ' + repr(float(obj.get(name, DEFAULTS[name]))))
    bezier = str(obj.get('easing.bezierCurve', ''))
    if bezier.strip():
        lines.append(child + 'easing.bezierCurve: ' + bezier)
    loops = int(obj.get('loops', 1))
    lines.append(child + 'loops: ' + ('Animation.Infinite' if loops == -1 else str(loops)))
    lines.append(child + 'running: ' + str(obj.get('running', 'false')))
    lines.append(indent + '}')
    return lines


CLASSES = (OBJECT_OT_add_qml_property_animation, OBJECT_PT_qml_property_animation)


def qml_property_animation_register():
    bpy.types.Object.qml_property_animation_easing_type = EnumProperty(
        name='Easing type', items=EASING_ITEMS, get=get_easing_type, set=set_easing_type)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def qml_property_animation_unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.qml_property_animation_easing_type
