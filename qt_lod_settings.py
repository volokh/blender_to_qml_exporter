"""Per-object Qt Quick 3D LOD settings in Object Constraints."""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Panel, PropertyGroup

from .qt_simplifier import MAX_LOD_LEVEL


def _mesh_object_poll(_self, obj):
    return obj.type == 'MESH'


class QtLodSettings(PropertyGroup):
    enabled: BoolProperty(name="Enable LOD Overrides", default=False)
    use_max: BoolProperty(name="Override Generated LOD Levels", default=False)
    max_levels: IntProperty(name="Maximum Generated LOD", default=7, min=0, max=MAX_LOD_LEVEL)


for _level in range(1, MAX_LOD_LEVEL + 1):
    QtLodSettings.__annotations__[f'lod{_level}'] = PointerProperty(
        name=f"LOD{_level}", type=bpy.types.Object, poll=_mesh_object_poll)
    QtLodSettings.__annotations__[f'use_distance{_level}'] = BoolProperty(
        name=f"Override LOD{_level} Distance", default=False)
    QtLodSettings.__annotations__[f'distance{_level}'] = FloatProperty(
        name=f"LOD{_level} Distance", default=0.0, min=0.0,
        description="Camera depth to the subset bounding box in scene units")


class OBJECT_PT_qt_lod_settings(Panel):
    bl_label = "Qt Quick 3D LOD"
    bl_idname = "OBJECT_PT_qt_lod_settings"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'constraint'

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        settings = context.object.qt_lod_settings
        layout.prop(settings, "enabled")
        column = layout.column()
        column.enabled = settings.enabled
        row = column.row()
        row.prop(settings, "use_max", text="")
        sub = row.row()
        sub.enabled = settings.use_max
        sub.prop(settings, "max_levels")
        column.label(text="Manual LOD Objects")
        for level in range(1, MAX_LOD_LEVEL + 1):
            column.prop(settings, f"lod{level}")
        column.label(text="Camera Distance Overrides")
        for level in range(1, MAX_LOD_LEVEL + 1):
            row = column.row()
            row.prop(settings, f"use_distance{level}", text="")
            sub = row.row()
            sub.enabled = getattr(settings, f"use_distance{level}")
            sub.prop(settings, f"distance{level}", text=f"LOD{level}")


def active_lod_settings(obj):
    settings = getattr(obj, 'qt_lod_settings', None)
    return settings if obj.type == 'MESH' and settings is not None and settings.enabled else None


def lod_settings_register():
    bpy.utils.register_class(QtLodSettings)
    bpy.types.Object.qt_lod_settings = PointerProperty(type=QtLodSettings)
    bpy.utils.register_class(OBJECT_PT_qt_lod_settings)


def lod_settings_unregister():
    bpy.utils.unregister_class(OBJECT_PT_qt_lod_settings)
    del bpy.types.Object.qt_lod_settings
    bpy.utils.unregister_class(QtLodSettings)
