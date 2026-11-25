import bpy
from bpy.types import Operator, Panel


class OBJECT_OT_add_qml_node_switcher(Operator):
    bl_idname = "object.add_qml_node_switcher"
    bl_label = "Qml.NodeSwitcher"
    bl_description = "Add a NodeSwitcher marker controlling its parent node's visibility"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = bpy.data.objects.new("Qml.NodeSwitcher", None)
        obj.empty_display_type = 'PLAIN_AXES'
        obj.empty_display_size = 0.25
        context.collection.objects.link(obj)
        obj.location = context.scene.cursor.location
        obj["qml_type"] = "Qml.NodeSwitcher"
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


def is_qml_node_switcher(obj):
    return obj.type == 'EMPTY' and obj.get("qml_type", "") == "Qml.NodeSwitcher"


class OBJECT_PT_qml_node_switcher(Panel):
    bl_label = "QML NodeSwitcher"
    bl_idname = "OBJECT_PT_qml_node_switcher"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None and is_qml_node_switcher(context.object)

    def draw(self, context):
        self.layout.prop(context.object, '["qml_type"]', text='Qml Type')


def export_qml_node_switcher(obj, nid, d):
    indent = "    " * d
    return [
        f'{indent}LM.NodeSwitcher {{',
        f'{indent}    view: parent',
        f'{indent}}}',
    ]


classes = (
    OBJECT_OT_add_qml_node_switcher,
    OBJECT_PT_qml_node_switcher,
)


def qml_node_switcher_register():
    for cls in classes:
        bpy.utils.register_class(cls)


def qml_node_switcher_unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
