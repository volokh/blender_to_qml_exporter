import bpy
from bpy.types import Operator, Menu
from .qt_hatch import qml_hatch_register, qml_hatch_unregister, is_qml_hatch, export_qml_hatch, OBJECT_OT_add_qml_hatch
from .qt_rheostat import qml_rheostat_register, qml_rheostat_unregister, is_qml_rheostat, export_qml_rheostat, OBJECT_OT_add_qml_rheostat
from .qt_animated_gauge import qml_animated_gauge_register, qml_animated_gauge_unregister, is_qml_animated_gauge, export_qml_animated_gauge, OBJECT_OT_add_qml_animated_gauge

# Shipmate plugin


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


def export_shipmate(obj, nid, data):
    lines_ = []
    if is_qml_hatch(obj):
        lines_ = export_qml_hatch(obj, nid, data)
    elif is_qml_rheostat(obj):
        lines_ = export_qml_rheostat(obj, nid, data)
    elif is_qml_animated_gauge(obj):
        lines_ = export_qml_animated_gauge(obj, nid, data)


    return lines_;


def draw_shipmate_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(VIEW3D_MT_shipmate_add.bl_idname, icon='OUTLINER_COLLECTION')


def shipmate_register():
    qml_hatch_register()
    qml_rheostat_register()
    qml_animated_gauge_register()
    bpy.utils.register_class(VIEW3D_MT_shipmate_add)
    bpy.types.VIEW3D_MT_add.append(draw_shipmate_menu)


def shipmate_unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_shipmate_menu)
    bpy.utils.unregister_class(VIEW3D_MT_shipmate_add)
    qml_animated_gauge_unregister()
    qml_rheostat_unregister()
    qml_hatch_unregister()
