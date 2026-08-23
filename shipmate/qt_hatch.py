import bpy
from bpy.types import Operator, Menu, Panel, PropertyGroup
from bpy.props import FloatProperty, StringProperty, PointerProperty, FloatVectorProperty


class QMLHatchProperties(PropertyGroup):
    qml_type: StringProperty(
        name="QML Type",
        default="Qml.Hatch",
        options={'HIDDEN'}
    )

    final_rotation: FloatVectorProperty(
        name="Open Rotation",
        default=(0., 0., 0.),
        description="Rotation in degrees for finalRotation"
    )

    hover_text: StringProperty(
        name="Hover text",
        default="Hatch",
        description="Hover text"
    )


class OBJECT_OT_add_qml_hatch(Operator):
    bl_idname = "object.add_qml_hatch"
    bl_label = "Qml.Hatch"
    bl_description = "Add a Qml.Hatch marker object"
    bl_options = {'REGISTER', 'UNDO'}

    final_rotation: FloatVectorProperty(
        name="Open Rotation",
        default=(0., 0., 0.),
        description="Rotation in degrees for finalRotation"
    )

    final_position: FloatVectorProperty(
        name="Open Position",
        default=(0., 0., 0.),
        description="Position in meters for finalPosition"
    )

    qml_type: StringProperty(
        name="QML Type",
        default="Qml.Hatch"
    )

    hover_text: StringProperty(
        name="Hover text",
        default="Hatch",
        description="Hover text"
    )

    value_out: StringProperty(
        name="ValueOut",
        description="Output value for the hatch"
    )

    validator: StringProperty(
        name="Validator",
        description="Validator value for the hatch"
    )

    def execute(self, context):
        empty = bpy.data.objects.new("Qml.Hatch", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.25

        context.collection.objects.link(empty)
        empty.location = context.scene.cursor.location

        # empty.qml_hatch.qml_type = "Qml.Hatch"
        # empty.qml_hatch.open_rotation = self.open_rotation

        empty["qml_type"] = self.qml_type
        empty["final_rotation"] = self.final_rotation
        empty["final_position"] = self.final_position
        empty["hover_text"] = self.hover_text
        empty["value_out"] = self.value_out
        empty["validator"] = self.validator

        for obj in context.selected_objects:
            obj.select_set(False)

        empty.select_set(True)
        context.view_layer.objects.active = empty

        return {'FINISHED'}


class OBJECT_PT_qml_hatch(Panel):
    bl_label = "QML Hatch"
    bl_idname = "OBJECT_PT_qml_hatch"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("qml_type", "") == "Qml.Hatch"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        layout.prop(obj, '["qml_type"]', text='Qml Type')
        layout.prop(obj, '["final_rotation"]', text='Final Rotation')
        layout.prop(obj, '["final_position"]', text='Final Position')
        layout.prop(obj, '["hover_text"]', text='Hover Text')
        layout.prop(obj, '["value_out"]', text='Output')
        layout.prop(obj, '["validator"]', text='Validator')


'''def menu_func_empty(self, context):
    self.layout.separator()
    self.layout.operator(
        OBJECT_OT_add_qml_hatch.bl_idname,
        text="Qml.Hatch",
        icon='EMPTY_AXIS'
    )
'''


classes = (
    QMLHatchProperties,
    OBJECT_OT_add_qml_hatch,
    OBJECT_PT_qml_hatch,
)


def is_qml_hatch(obj):
    return obj.type == 'EMPTY' and obj.get("qml_type", "") == "Qml.Hatch"


def I(n):
    return "    " * n


def qml_hatch_final_rotation(obj):
    return tuple(obj.get("final_rotation", (0., 0., 0.)))

def qml_hatch_final_position(obj):
    return tuple(obj.get("final_position", (0., 0., 0.)))


def qml_hatch_hover_text(obj):
    return obj.get("hover_text", "")


def qml_hatch_output_value(obj):
    return obj.get("value_out", None)

def qml_hatch_validator(obj):
    return obj.get("validator", None)



def qt_pos(value):
    """Blender Z-up → Qt Y-up coordinate conversion."""
    """Blender (X right, Y fwd, Z up)  →  Qt Quick 3D (X right, Y up, -Z fwd)"""

    value_ = tuple(value)
    return (value_[0], value_[2], -value_[1])


def export_qml_hatch(obj, nid, d):
    lines = [f'{I(d)}LM.Hatch {{',
             # f'{I(d+1)}id: {nid}',
             f'{I(d+1)}node: parent',
             f'{I(d+1)}finalRotation: Qt.vector3d{qt_pos(qml_hatch_final_rotation(obj))}',
             f'{I(d+1)}finalPosition: Qt.vector3d{qt_pos(qml_hatch_final_position(obj))}'
            ]

    hover_text = qml_hatch_hover_text(obj)
    if hover_text:
        lines += [f'{I(d+1)}picker.hoverText: `{hover_text}`']

    out_value_ = qml_hatch_output_value(obj)
    if out_value_:
        lines += [f'{I(d+1)}onIsFinalChanged: {out_value_}']

    validator_ = qml_hatch_validator(obj)
    if validator_:
         lines += [f'{I(d+1)}validator: {validator_}']

    lines += [f'{I(d)}}}']
    return lines


def qml_hatch_register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # bpy.types.Object.qml_hatch = PointerProperty(type=QMLHatchProperties)
    # bpy.types.VIEW3D_MT_add.append(draw_shipmate_menu)


def qml_hatch_unregister():
    # bpy.types.VIEW3D_MT_add.remove(draw_shipmate_menu)
    # del bpy.types.Object.qml_hatch

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    qml_hatch_register()
