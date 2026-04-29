# This Python file uses the following encoding: utf-8

import bpy
from bpy.types import Operator, Menu, Panel, PropertyGroup
from bpy.props import FloatProperty, StringProperty, PointerProperty, FloatVectorProperty, BoolProperty


class QMLAnimatedGaugeProperties(PropertyGroup):
    qml_type: StringProperty(
        name="QML Type",
        default="Qml.AnimatedGauge",
        options={'HIDDEN'}
    )

    change_step: FloatVectorProperty(
        name="Step",
        default=(0., 0., 0.),
        description="Change step in degrees"
    )

    change_duration: FloatProperty(
        name="Change Duration",
        default=1000.0,
        description="Duration of the change in seconds"
    )

    min_value: FloatProperty(
        name="Min Value",
        default=0.0,
        description="Minimum value for the animated gauge"
    )

    max_value: FloatProperty(
        name="Max Value",
        default=0.0,
        description="Maximum value for the animated gauge"
    )

    value: FloatProperty(
        name="Value",
        default=0.0,
        description="Default value for the animated gauge"
    )

    initial_value: FloatProperty(
        name="Initial Value",
        default=0.0,
        description="Initial value for the animated gauge"
    )



class OBJECT_OT_add_qml_animated_gauge(Operator):
    bl_idname = "object.add_qml_animated_gauge"
    bl_label = "Qml.AnimatedGauge"
    bl_description = "Add a Qml.AnimatedGauge marker object"
    bl_options = {'REGISTER', 'UNDO'}

    qml_type: StringProperty(
        name="QML Type",
        default="Qml.AnimatedGauge",
        options={'HIDDEN'}
    )

    hover_text: StringProperty(
        name="Hover text",
        #default="Rheostat switch",
        description="Hover text"
    )

    change_grade: FloatVectorProperty(
        name="Step",
        default=(0., 0., 0.),
        description="Change grade in units"
    )

    change_duration: FloatProperty(
        name="Change Duration",
        default=1000.0,
        description="Duration of the change in seconds"
    )

    value: FloatVectorProperty(
        name="MDM Values",
        default=(0.0, 0.,0.),
        description="Minimum|Default|Maximum value for the animated gauge"
    )

    rotate: BoolProperty(
        name="Rotate",
        default=True,
        description="Whether to rotate or move the gauge based on the change step"
    )

    grade: FloatProperty(
        name="Grade Value",
        default=1.0,
        description="Grade value for the animated gauge"
    )

    initial_value: FloatProperty(
        name="Initial Value",
        default=0.0,
        description="Default value for the animated gauge"
    )

    value_in: StringProperty(
        name="ValueInput",
        description="Input value for the animated gauge"
    )

    def execute(self, context):
        empty = bpy.data.objects.new("Qml.AnimatedGauge", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.25

        context.collection.objects.link(empty)
        empty.location = context.scene.cursor.location

        # empty.qml_hatch.qml_type = "Qml.Hatch"
        # empty.qml_hatch.open_rotation = self.open_rotation

        empty["qml_type"] = self.qml_type
        empty["change_grade"] = self.change_grade
        empty["change_duration"] = self.change_duration
        empty["grade"] = self.grade
        empty["hover_text"] = self.hover_text
        empty["value"] = self.value
        empty["initial_value"] = self.initial_value
        empty["rotate"] = self.rotate
        empty["value_in"] = self.value_in

        for obj in context.selected_objects:
            obj.select_set(False)

        empty.select_set(True)
        context.view_layer.objects.active = empty

        return {'FINISHED'}


'''class VIEW3D_MT_shipmate_add(Menu):
    bl_label = "Shipmate"
    bl_idname = "VIEW3D_MT_shipmate_add"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            OBJECT_OT_add_qml_rheostat.bl_idname,
            text="Qml.AnimatedGauge",
            icon='EMPTY_AXIS'
        )
'''


class OBJECT_PT_qml_animated_gauge(Panel):
    bl_label = "QML Animated Gauge"
    bl_idname = "OBJECT_PT_qml_animated_gauge"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("qml_type", "") == "Qml.AnimatedGauge"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        layout.prop(obj, '["qml_type"]', text='Qml Type')
        layout.prop(obj, '["change_grade"]', text='Change Grade')
        layout.prop(obj, '["change_duration"]', text='Change Duration')
        layout.prop(obj, '["value"]', text='MDM Values')
        layout.prop(obj, '["grade"]', text='Grade')
        layout.prop(obj, '["hover_text"]', text='Hover Text')
        layout.prop(obj, '["initial_value"]', text='Initial Value')
        layout.prop(obj, '["rotate"]', text='Rotate instead of Move')
        layout.prop(obj, '["value_in"]', text='Input Value')


'''def menu_func_empty(self, context):
    self.layout.separator()
    self.layout.operator(
        OBJECT_OT_add_qml_rheostat.bl_idname,
        text="Qml.AnimatedGauge",
        icon='EMPTY_AXIS'
    )
'''

'''def draw_shipmate_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(VIEW3D_MT_shipmate_add.bl_idname, icon='OUTLINER_COLLECTION')
'''

classes = (
    QMLAnimatedGaugeProperties,
    OBJECT_OT_add_qml_animated_gauge,
    # VIEW3D_MT_shipmate_add,
    OBJECT_PT_qml_animated_gauge,
)


def is_qml_animated_gauge(obj):
    return obj.type == 'EMPTY' and obj.get("qml_type", "") == "Qml.AnimatedGauge"


def I(n):
    return "    " * n


def qml_animated_gauge_change_step(obj):
    return tuple(obj.get("change_step", (0., 0., 0.)))

def qml_animated_gauge_value(obj):
    return tuple(obj.get("value", (0., 0., 0.)))

def qml_animated_gauge_duration(obj):
    return obj.get("change_duration", 1000.0)

def qml_animated_gauge_change_grade(obj):
    return obj.get("change_grade", 1.0)

def qml_animated_gauge_hover_text(obj):
    return obj.get("hover_text", "")

def qml_animated_gauge_initial_value(obj):
    return obj.get("initial_value", 0.0)

def qml_animated_gauge_input_value(obj):
    return obj.get("value_in", None)


def qt_pos(value):
    """Blender Z-up → Qt Y-up coordinate conversion."""
    """Blender (X right, Y fwd, Z up)  →  Qt Quick 3D (X right, Y up, -Z fwd)"""

    value_ = tuple(value)
    return (value_[0], value_[2], -value_[1])


def export_qml_animated_gauge(obj, nid, d):
    value_ = qml_animated_gauge_value(obj)
    input_value_ = qml_animated_gauge_input_value(obj)
    lines = [f'{I(d)}LM.AnimatedGauge {{',
             # f'{I(d+1)}id: {nid}',
             f"{I(d+1)}objectName: '{obj.name}'",
             f'{I(d+1)}node: parent',
             f'{I(d+1)}minValue: {value_[0]}',
             f'{I(d+1)}maxValue: {value_[2]}',
             f'{I(d+1)}value: {input_value_ if input_value_ else value_[1]}',
             f'{I(d+1)}changeGrade: Qt.vector3d{qt_pos(qml_animated_gauge_change_grade(obj))}',
             #f'{I(d+1)}changeStep: Qt.vector3d{qt_pos(qml_animated_gauge_change_step(obj))}',
             f'{I(d+1)}anim.duration: {qml_animated_gauge_duration(obj)}',
             #f'{I(d+1)}initialValue: {qml_animated_gauge_initial_value(obj)}',
             f'{I(d+1)}picker.parent: node.parent',
             ]

    hover_text = qml_animated_gauge_hover_text(obj)
    if hover_text:
        lines += [f'{I(d+1)}picker.hoverText: `{hover_text}`']

    lines += [f'{I(d)}}}']
    return lines


def qml_animated_gauge_register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # bpy.types.Object.qml_hatch = PointerProperty(type=QMLHatchProperties)
    # bpy.types.VIEW3D_MT_add.append(draw_shipmate_menu)


def qml_animated_gauge_unregister():
    # bpy.types.VIEW3D_MT_add.remove(draw_shipmate_menu)
    # del bpy.types.Object.qml_hatch

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)



if __name__ == "__main__":
    qml_animated_gauge_register()

