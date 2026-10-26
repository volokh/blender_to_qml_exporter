import bpy
from bpy.types import Operator, Menu, Panel, PropertyGroup
from bpy.props import BoolProperty, FloatProperty, StringProperty, PointerProperty, FloatVectorProperty


class QMLRheostatProperties(PropertyGroup):
    stepPositiveSound: StringProperty(
        name="Positive step sound",
        default="",
        subtype='FILE_PATH',
        description="Optional movement sound URL or audio file; plays only while the control moves"
    )

    stepNegativeSound: StringProperty(
        name="Negative step sound",
        default="",
        subtype='FILE_PATH',
        description="Optional movement sound URL or audio file; plays only while the control moves"
    )

    sequentialMode: BoolProperty(
        name="Sequential Mode",
        default=False,
        description="Wait for each physical lever movement before accepting another scroll step"
    )

    qml_type: StringProperty(
        name="QML Type",
        default="Qml.Rheostat",
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
        description="Minimum value for the rheostat"
    )

    max_value: FloatProperty(
        name="Max Value",
        default=0.0,
        description="Maximum value for the rheostat"
    )

    value: FloatProperty(
        name="Value",
        default=0.0,
        description="Default value for the rheostat"
    )

    initial_value: FloatProperty(
        name="Initial Value",
        default=0.0,
        description="Initial value for the rheostat"
    )


class OBJECT_OT_add_qml_rheostat(Operator):
    stepPositiveSound: StringProperty(
        name="Positive step sound",
        default="",
        subtype='FILE_PATH',
        description="Optional movement sound URL or audio file; plays only while the control moves"
    )

    stepNegativeSound: StringProperty(
        name="Negative step sound",
        default="",
        subtype='FILE_PATH',
        description="Optional movement sound URL or audio file; plays only while the control moves"
    )

    sequentialMode: BoolProperty(
        name="Sequential Mode",
        default=False,
        description="Wait for each physical lever movement before accepting another scroll step"
    )

    bl_idname = "object.add_qml_rheostat"
    bl_label = "Qml.Rheostat"
    bl_description = "Add a Qml.Rheostat marker object"
    bl_options = {'REGISTER', 'UNDO'}

    qml_type: StringProperty(
        name="QML Type",
        default="Qml.Rheostat",
        options={'HIDDEN'}
    )

    hover_text: StringProperty(
        name="Hover text",
        default="Rheostat switch",
        description="Hover text"
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

    value: FloatVectorProperty(
        name="MDM Values",
        default=(0.0, 0.,0.),
        description="Minimum|Default|Maximum value for the rheostat"
    )

    step: FloatProperty(
        name="Step Value",
        default=1.0,
        description="Step value for the rheostat"
    )

    initial_value: FloatProperty(
        name="Initial Value",
        default=0.0,
        description="Default value for the rheostat"
    )

    value_out: StringProperty(
        name="ValueOut",
        description="Output value for the rheostat"
    )

    blocker_visible: StringProperty(
        name="Blocker Visible",
        description="Blocker visible value for the rheostat"
    )

    blocker_text: StringProperty(
        name="Blocker Text",
        description="Blocker Text value for the rheostat"
    )

    validator: StringProperty(
        name="Validator",
        description="Validator value for the rheostat"
    )

    def execute(self, context):
        empty = bpy.data.objects.new("Qml.Rheostat", None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.25

        context.collection.objects.link(empty)
        empty.location = context.scene.cursor.location

        # empty.qml_hatch.qml_type = "Qml.Hatch"
        # empty.qml_hatch.open_rotation = self.open_rotation

        empty["stepPositiveSound"] = self.stepPositiveSound
        empty["stepNegativeSound"] = self.stepNegativeSound
        empty["sequentialMode"] = self.sequentialMode
        empty["qml_type"] = self.qml_type
        empty["change_step"] = self.change_step
        empty["change_duration"] = self.change_duration
        empty["step"] = self.step
        empty["hover_text"] = self.hover_text
        empty["value"] = self.value
        empty["initial_value"] = self.initial_value
        empty["value_out"] = self.value_out
        empty["blocker_visible"] = self.blocker_visible
        empty["blocker_text"] = self.blocker_text
        empty["validator"] = self.validator

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
            text="Qml.Rheostat",
            icon='EMPTY_AXIS'
        )
'''


class OBJECT_PT_qml_rheostat(Panel):
    bl_label = "QML Rheostat"
    bl_idname = "OBJECT_PT_qml_rheostat"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("qml_type", "") == "Qml.Rheostat"

    def draw(self, context):
        layout = self.layout
        obj = context.object

        layout.prop(obj, '["qml_type"]', text='Qml Type')
        layout.prop(obj, '["change_step"]', text='Change Step')
        layout.prop(obj, '["change_duration"]', text='Change Duration')
        layout.prop(obj, '["value"]', text='MDM Values')
        layout.prop(obj, '["step"]', text='Step')
        layout.prop(obj, '["hover_text"]', text='Hover Text')
        layout.prop(obj, '["initial_value"]', text='Initial Value')
        layout.prop(obj, '["value_out"]', text='Output')
        layout.prop(obj, '["blocker_visible"]', text='Blocker Visible')
        layout.prop(obj, '["blocker_text"]', text='Blocker Text')
        layout.prop(obj, '["validator"]', text='Validator')
        layout.prop(obj, 'qml_hatch_step_positive_sound', text='Step Positive Sound')
        layout.prop(obj, 'qml_hatch_step_negative_sound', text='Step Negative Sound')
        layout.prop(obj, 'qml_rheostat_sequential_mode', text='Sequential Mode')


'''def menu_func_empty(self, context):
    self.layout.separator()
    self.layout.operator(
        OBJECT_OT_add_qml_rheostat.bl_idname,
        text="Qml.Rheostat",
        icon='EMPTY_AXIS'
    )
'''

'''def draw_shipmate_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(VIEW3D_MT_shipmate_add.bl_idname, icon='OUTLINER_COLLECTION')
'''

classes = (
    QMLRheostatProperties,
    OBJECT_OT_add_qml_rheostat,
    # VIEW3D_MT_shipmate_add,
    OBJECT_PT_qml_rheostat,
)


def is_qml_rheostat(obj):
    return obj.type == 'EMPTY' and obj.get("qml_type", "") == "Qml.Rheostat"


def I(n):
    return "    " * n


def qml_rheostat_change_step(obj):
    return tuple(obj.get("change_step", (0., 0., 0.)))


def qml_rheostat_value(obj):
    return tuple(obj.get("value", (0., 0., 0.)))

def qml_rheostat_duration(obj):
    return obj.get("change_duration", 1000.0)

def qml_rheostat_step(obj):
    return obj.get("step", 1.0)

def qml_rheostat_hover_text(obj):
    return obj.get("hover_text", "")

def qml_rheostat_initial_value(obj):
    return obj.get("initial_value", 0.0)


def qml_rheostat_output_value(obj):
    return obj.get("value_out", None)


def qml_rheostat_blocker_visible(obj):
    return obj.get("blocker_visible", None)

def qml_rheostat_blocker_text(obj):
    return obj.get("blocker_text", None)

def qml_rheostat_validator(obj):
    return obj.get("validator", None)

def get_step_pos_sound(obj):
    return obj.get("stepPositiveSound", '')

def set_step_pos_sound(obj, value):
    obj["stepPositiveSound"] = value


def get_step_neg_sound(obj):
    return obj.get("stepNegativeSound", '')


def set_step_neg_sound(obj, value):
    obj["stepNegativeSound"] = value


def qt_pos(value):
    """Blender Z-up → Qt Y-up coordinate conversion."""
    """Blender (X right, Y fwd, Z up)  →  Qt Quick 3D (X right, Y up, -Z fwd)"""

    value_ = tuple(value)
    return (value_[0], value_[2], -value_[1])


def export_qml_rheostat(obj, nid, d, with_object_name=True):
    value_ = qml_rheostat_value(obj)
    out_value_ = qml_rheostat_output_value(obj)
    lines = [f'{I(d)}LM.RheostatButton {{',
             # f'{I(d+1)}id: {nid}',
             f"{I(d+1)}objectName: '{obj.name}'" if with_object_name else "",
             f'{I(d+1)}node: parent',
             f'{I(d+1)}minValue: {value_[0]}',
             f'{I(d+1)}maxValue: {value_[2]}',
             f'{I(d+1)}value: {value_[1]}',
             f'{I(d+1)}step: {qml_rheostat_step(obj)}',
             f'{I(d+1)}changeStep: Qt.vector3d{qt_pos(qml_rheostat_change_step(obj))}',
             f'{I(d+1)}changeDuration: {qml_rheostat_duration(obj)}',
             f'{I(d+1)}initialValue: {qml_rheostat_initial_value(obj)}'
             ]

    hover_text_ = qml_rheostat_hover_text(obj)
    if hover_text_:
        lines += [f'{I(d+1)}picker.hoverText: `{hover_text_}`']

    if out_value_:
         lines += [f'{I(d+1)}onValueChanged: {out_value_}']

    blocker_visible_ = qml_rheostat_blocker_visible(obj)
    if blocker_visible_:
         lines += [f'{I(d+1)}blocker.visible: {blocker_visible_}']

    blocker_text_ = qml_rheostat_blocker_text(obj)
    if blocker_text_:
         lines += [f'{I(d+1)}blocker.text: {blocker_text_}']

    validator_ = qml_rheostat_validator(obj)
    if validator_:
         lines += [f'{I(d+1)}validator: {validator_}']

    stepPositiveSound_ = get_step_pos_sound(obj)
    if stepPositiveSound_:
        lines += [f'{I(d+1)}wheelPositiveSound: "{stepPositiveSound_}"']

    stepNegativeSound_ = get_step_neg_sound(obj)
    if stepNegativeSound_:
        lines += [f'{I(d+1)}wheelNegativeSound: "{stepNegativeSound_}"']

    if obj.get("sequentialMode", False):
        lines += [f'{I(d+1)}sequentialMode: true']

    lines += [f'{I(d)}}}']
    return lines


def get_sequential_mode(obj):
    return bool(obj.get("sequentialMode", False))


def set_sequential_mode(obj, value):
    obj["sequentialMode"] = value


def qml_rheostat_register():
    # RNA proxies expose new options even on markers created before these fields existed.
    bpy.types.Object.qml_hatch_step_positive_sound = StringProperty(
        name="Step Positive Sound", subtype='FILE_PATH', get=get_step_pos_sound, set=set_step_pos_sound)

    bpy.types.Object.qml_hatch_step_negative_sound = StringProperty(
        name="Step Negative Sound", subtype='FILE_PATH', get=get_step_neg_sound, set=set_step_neg_sound)

    #bpy.types.Object.qml_rheostat_step_sound = StringProperty(
    #    name="Step Sound", subtype='FILE_PATH', get=get_step_sound, set=set_step_sound)
    bpy.types.Object.qml_rheostat_sequential_mode = BoolProperty(
        name="Sequential Mode", get=get_sequential_mode, set=set_sequential_mode)

    for cls in classes:
        bpy.utils.register_class(cls)

    # bpy.types.Object.qml_hatch = PointerProperty(type=QMLHatchProperties)
    # bpy.types.VIEW3D_MT_add.append(draw_shipmate_menu)


def qml_rheostat_unregister():
    del bpy.types.Object.qml_hatch_step_positive_sound
    del bpy.types.Object.qml_hatch_step_negative_sound
    del bpy.types.Object.qml_rheostat_sequential_mode
    # bpy.types.VIEW3D_MT_add.remove(draw_shipmate_menu)
    # del bpy.types.Object.qml_hatch

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)



if __name__ == "__main__":
    qml_rheostat_register()
