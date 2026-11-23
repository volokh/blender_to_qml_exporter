"""Run with Blender --background --factory-startup --python this_file.py."""
import importlib.util
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy

addon_root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "object_linked_material_export_test",
    addon_root / "__init__.py",
    submodule_search_locations=[str(addon_root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

mesh = bpy.data.meshes.new("SharedMaterialMesh")
mesh.from_pydata(
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
    [],
    [(0, 1, 2), (1, 3, 2)],
)
mesh.materials.append(bpy.data.materials.new("DataLinkedMaterial"))
mesh.materials.append(bpy.data.materials.new("SecondSlotMaterial"))
mesh.polygons[0].material_index = 0
mesh.polygons[1].material_index = 1

data_linked = bpy.data.objects.new("DataLinkedObject", mesh)
object_linked = bpy.data.objects.new("ObjectLinkedObject", mesh)
bpy.context.collection.objects.link(data_linked)
bpy.context.collection.objects.link(object_linked)
slot = object_linked.material_slots[0]
slot.link = 'OBJECT'
slot.material = bpy.data.materials.new("ObjectOverrideMaterial")

output_dir = Path(tempfile.mkdtemp(prefix="blender-object-material-"))
settings = SimpleNamespace(
    report=lambda *_args: None,
    apply_modifiers=False,
    convert_coords=False,
    generate_lods=False,
    manual_lods=False,
)
exporter = addon.BalsamExporter(str(output_dir / "scene.qml"), settings)
data_linked_qml = "\n".join(exporter._obj_qml(data_linked))
object_linked_qml = "\n".join(exporter._obj_qml(object_linked))

source_re = re.compile(r'\bsource: "([^"]+\.mesh)"')
data_source = source_re.search(data_linked_qml)
object_source = source_re.search(object_linked_qml)
assert data_source and object_source
assert data_source.group(1) == object_source.group(1), (data_linked_qml, object_linked_qml)
assert len(exporter.exp_meshes) == 1, exporter.exp_meshes
assert "DataLinkedMaterial" in data_linked_qml
assert "ObjectOverrideMaterial" not in data_linked_qml
assert "ObjectOverrideMaterial" in object_linked_qml
assert "SecondSlotMaterial" in object_linked_qml

cached_mesh = next(iter(exporter.exp_meshes.values()))
assert cached_mesh["material_slot_indices"] == [0, 1], cached_mesh
print("OBJECT_LINKED_MATERIAL_EXPORT_TEST_OK")
