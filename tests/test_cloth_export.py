"""Run: Blender --background --factory-startup --python tests/test_cloth_export.py"""
import bpy
import importlib.util
import sys
import tempfile
import struct
from pathlib import Path
from types import SimpleNamespace

addon = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cloth_export_test', addon/'__init__.py', submodule_search_locations=[str(addon)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
writer = sys.modules[spec.name+'.qt_mesh_writer']
reader = sys.modules[spec.name+'.qt_mesh_importer']
mesh = bpy.data.meshes.new('ClothGeometry')
verts = [(x*.5, 0, z*.5) for z in range(3) for x in range(4)]
faces = [(z*4+x, z*4+x+1, (z+1)*4+x+1, (z+1)*4+x) for z in range(2) for x in range(3)]
mesh.from_pydata(verts, [], faces)
obj = bpy.data.objects.new('ClothFlag', mesh)
bpy.context.collection.objects.link(obj)
obj.location = (3,4,5)
obj.scale = (2,1,3)
uv = mesh.uv_layers.new(name='FabricUV')
for loop in mesh.loops:
    v = mesh.vertices[loop.vertex_index].co
    uv.data[loop.index].uv = (v.x/1.5, v.z)
uv_before = [tuple(v.uv) for v in uv.data]
for name, color in [('RedFabric',(1,0,0,1)),('BlueFabric',(0,0,1,1))]:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = color
    image = bpy.data.images.new(name+'Texture', width=4,height=4,alpha=True)
    image.pixels = list(color)*16
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = image
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    mesh.materials.append(mat)
for polygon in mesh.polygons:
    polygon.material_index = polygon.index % 2
pin = obj.vertex_groups.new(name='PolePins')
pin.add([0,4,8],1,'REPLACE')
pin.add([1,5,9],.35,'REPLACE')
cloth = obj.modifiers.new('SailingCloth','CLOTH')
cloth.settings.vertex_group_mass = pin.name
bpy.context.view_layer.update()
settings = SimpleNamespace(report=lambda *args:None,apply_modifiers=True,convert_coords=True,generate_lods=True)
out = Path(tempfile.mkdtemp(prefix='blender-cloth-'))
e = module.BalsamExporter(str(out/'scene.qml'), settings)
qml = '\n'.join(e._obj_qml(obj))
assert 'LM.Flag {' in qml and 'meshSource:' in qml, qml
assert 'clothOrigin:' in qml and 'vertexPinWeights: true' in qml
assert 'materials: [' in qml and len(e.exp_materials)==4
assert len(e.exp_images)==2
assert sum('LM.FlagMaterial {' in q for _,q in e.exp_materials.values()) == 2
assert '_flag' in qml
assert cloth.show_viewport and cloth.show_render, 'Modifier state was not restored'
assert [tuple(v.uv) for v in mesh.uv_layers.active.data]==uv_before
exported = next(iter(e.exp_meshes.values()))
qtmesh = reader.read_qt_mesh_file(out/exported['source'])[0]
assert len(qtmesh.subsets)==2 and not any(s.lods for s in qtmesh.subsets)
attrs = {entry.name:entry for entry in qtmesh.vertex_entries}
position_attr = attrs['attr_pos']
positions = {tuple(round(v,5) for v in struct.unpack_from('<3f',qtmesh.vertex_buffer,i*qtmesh.stride+position_attr.offset)) for i in range(qtmesh.vertex_count)}
assert positions == {(round(x,5),round(z,5),round(-y,5)) for x,y,z in verts}, 'Authored geometry changed'
assert all(s.bounds_min[0] < -1 and s.bounds_max[0] > 2 for s in qtmesh.subsets), 'Wind culling bounds are too small'
color_attr = attrs['attr_color']
weights = [struct.unpack_from('<4f',qtmesh.vertex_buffer,i*qtmesh.stride+color_attr.offset)[3] for i in range(qtmesh.vertex_count)]
assert any(abs(w-.35)<1e-5 for w in weights) and 1 in weights and 0 in weights
obj['windStrength']=8
obj['windDirection']=45
qml2='\n'.join(e._obj_qml(obj))
assert 'windStrength: 8.0' in qml2 and 'windDirection: 45.0' in qml2
(out/'ClothFixture.qml').write_text('import QtQuick\nimport QtQuick3D\nimport LogicModule as LM\nNode {\n' + '\n'.join(q for _,q in e.exp_materials.values()) + '\n' + qml + '\n}\n')
# Distinct cloth objects sharing a datablock must not accidentally share pin/control data.
settings.apply_modifiers=False
clone=obj.copy()
clone.name='ClothFlagCopy'
bpy.context.collection.objects.link(clone)
shared=module.BalsamExporter(str(out/'shared.qml'),settings)
shared._obj_qml(obj)
shared._obj_qml(clone)
assert len(shared.exp_meshes)==2
settings.apply_modifiers=True
cloth.show_render=False
ordinary=module.BalsamExporter(str(out/'ordinary.qml'),settings)
assert 'LM.Flag {' not in '\n'.join(ordinary._obj_qml(obj))
print('PASS: real cloth mesh, material subsets, textures, UVs, graded pin weights, transforms, no LODs, modifier restoration, overrides, disabled cloth')
print('CLOTH_FIXTURE='+str(out))
