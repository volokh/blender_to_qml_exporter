import bpy
from bpy.types import Operator, Menu
from .qt_hatch import qml_hatch_register, qml_hatch_unregister, is_qml_hatch, export_qml_hatch, OBJECT_OT_add_qml_hatch
from .qt_rheostat import qml_rheostat_register, qml_rheostat_unregister, is_qml_rheostat, export_qml_rheostat, OBJECT_OT_add_qml_rheostat
from .qt_animated_gauge import qml_animated_gauge_register, qml_animated_gauge_unregister, is_qml_animated_gauge, export_qml_animated_gauge, OBJECT_OT_add_qml_animated_gauge
from .qt_hoverable_mat_switcher import qml_hoverable_mat_switcher_register, qml_hoverable_mat_switcher_unregister, is_qml_hoverable_mat_switcher, export_qml_hoverable_mat_switcher, OBJECT_OT_add_qml_hoverable_mat_switcher
from .qt_node_switcher import qml_node_switcher_register, qml_node_switcher_unregister, is_qml_node_switcher, export_qml_node_switcher, OBJECT_OT_add_qml_node_switcher

from .qt_property_animation import (
    DEFAULTS as PROPERTY_ANIMATION_DEFAULTS,
    qml_property_animation_register, qml_property_animation_unregister,
    is_qml_property_animation, export_qml_property_animation, OBJECT_OT_add_qml_property_animation,
)

# Shipmate plugin


SHIPMATE_CUSTOM_PROPERTIES = {
    'Qml.Hatch': {
        'qml_type', 'final_rotation', 'final_position', 'hover_text', 'value_out',
        'validator', 'stepPositiveSound', 'stepNegativeSound',
    },
    'Qml.Rheostat': {
        'qml_type', 'change_step', 'change_duration', 'step', 'hover_text', 'value',
        'initial_value', 'value_out', 'blocker_visible', 'blocker_text', 'validator',
        'stepPositiveSound', 'stepNegativeSound', 'sequentialMode',
    },
    'Qml.AnimatedGauge': {
        'qml_type', 'change_grade', 'change_step', 'change_duration', 'grade',
        'hover_text', 'value', 'initial_value', 'rotate', 'value_in',
    },
    'Qml.HoverableMatSwitcher': {'qml_type'},
    'Qml.NodeSwitcher': {'qml_type'},
    'Qml.PropertyAnimation': set(PROPERTY_ANIMATION_DEFAULTS),
}


def shipmate_custom_property_names(obj):
    return SHIPMATE_CUSTOM_PROPERTIES.get(obj.get('qml_type')) if obj.type == 'EMPTY' else None


class VIEW3D_MT_shipmate_add(Menu):
    bl_label = "Shipmate"
    bl_idname = "VIEW3D_MT_shipmate_add"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            OBJECT_OT_add_qml_hatch.bl_idname,
            text="Qml.Hatch",
            icon='EMPTY_AXIS'
        )
        layout.operator(
            OBJECT_OT_add_qml_rheostat.bl_idname,
            text="Qml.Rheostat",
            icon='EMPTY_AXIS'
        )
        layout.operator(
            OBJECT_OT_add_qml_animated_gauge.bl_idname,
            text="Qml.AnimatedGauge",
            icon='EMPTY_AXIS'
        )
        layout.operator(
            OBJECT_OT_add_qml_property_animation.bl_idname,
            text="Qml.PropertyAnimation",
            icon='ANIM',
        )
        layout.operator(
            OBJECT_OT_add_qml_hoverable_mat_switcher.bl_idname,
            text="Qml.HoverableMatSwitcher",
            icon='ANIM',
        )
        layout.operator(
            OBJECT_OT_add_qml_node_switcher.bl_idname,
            text="Qml.NodeSwitcher",
            icon='EMPTY_AXIS',
        )


def export_shipmate(obj, nid, data, parent_id=None, with_object_name=True):
    lines_ = []
    if is_qml_property_animation(obj):
        lines_ = export_qml_property_animation(obj, nid, data, parent_id)
    elif is_qml_hatch(obj):
        lines_ = export_qml_hatch(obj, nid, data)
    elif is_qml_rheostat(obj):
        lines_ = export_qml_rheostat(
            obj, nid, data, with_object_name=with_object_name)
    elif is_qml_animated_gauge(obj):
        lines_ = export_qml_animated_gauge(
            obj, nid, data, with_object_name=with_object_name)
    elif is_qml_hoverable_mat_switcher(obj):
        lines_ = export_qml_hoverable_mat_switcher(obj, nid, data)
    elif is_qml_node_switcher(obj):
        lines_ = export_qml_node_switcher(obj, nid, data)

    return lines_


def draw_shipmate_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(VIEW3D_MT_shipmate_add.bl_idname, icon='OUTLINER_COLLECTION')


def shipmate_register():
    qml_hatch_register()
    qml_rheostat_register()
    qml_animated_gauge_register()
    qml_property_animation_register()
    qml_hoverable_mat_switcher_register()
    qml_node_switcher_register()
    bpy.utils.register_class(VIEW3D_MT_shipmate_add)
    bpy.types.VIEW3D_MT_add.append(draw_shipmate_menu)


def shipmate_unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_shipmate_menu)
    bpy.utils.unregister_class(VIEW3D_MT_shipmate_add)
    qml_node_switcher_unregister()
    qml_hoverable_mat_switcher_unregister()
    qml_property_animation_unregister()
    qml_animated_gauge_unregister()
    qml_rheostat_unregister()
    qml_hatch_unregister()
