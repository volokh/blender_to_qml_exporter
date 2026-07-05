from bpy.types import Operator, Menu
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty,
    FloatProperty, IntProperty
)
from bpy_extras.io_utils import ExportHelper, ImportHelper
from .qt_mesh_writer import write_mesh_file, extract_mesh_data, material_id_for_name
from .qt_mesh_importer import QtMeshImportError, import_qt_mesh_file
from .qt_mesh_validate import validate_qt_mesh
from .qt_bsdf_mat_importer import mat_to_quick3d
from .shipmate.qt_shipmate import shipmate_register, shipmate_unregister, export_shipmate
from mathutils import Vector, Euler
from pathlib import Path
import re
import json
import struct
import math
import bmesh
import bpy
import uuid
import shutil
import hashlib
from mathutils import Matrix

MESH_EXPORT_OBJECT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT'}
LOD_LEVELS = (
    {"level": 1, "ratio": 0.55, "distance": .05},
    {"level": 2, "ratio": 0.25, "distance": 0.10},
    {"level": 3, "ratio": 0.08, "distance": 1.0},
    {"level": 4, "ratio": None, "distance": 10.0},
)

bl_info = {
    "name": "Qt Quick 3D Balsam Exporter Plugin",
    "author": "konvol",
    "version": (2, 2, 0),
    "blender": (4, 4, 0),
    "location": "File > Import/Export > Qt Quick 3D",
    "description": "Export Qt Quick 3D QML/native .mesh assets and import Qt Quick 3D .mesh files",
    "category": "Import-Export",
}


# ─────────────────────────────────────────────────────────────────
#  Qt .mesh binary format constants
#  Reverse-engineered from:
#    qtquick3d/src/utils/qssgmesh_p.h  (Qt 6.6, FILE_VERSION = 7)
#  @sa /opt/Qt/6.11.0/Src/qtquick3d/src/utils/qssgmesh.cpp
# ─────────────────────────────────────────────────────────────────

MESH_FILE_ID = 3365961549
MESH_FILE_VERSION = 7
MESH_FLAGS = 0
MULTI_MESH_FILE_ID = 555777497    # MultiMeshInfo::FILE_ID
MULTI_MESH_FILE_VERSION = 1
MESH_DATA_FILE_ID = 3365961549   # MeshDataHeader::FILE_ID
# latest (supports morph split, LODs, lightmaps)
MESH_DATA_FILE_VERSION = 7

COMPONENT_TYPE_UNSIGNED_INT16 = 4
COMPONENT_TYPE_UNSIGNED_INT32 = 6
COMPONENT_TYPE_FLOAT32 = 10

DRAW_MODE_TRIANGLES = 7
DRAW_MODE_LINES = 4

WINDING_CLOCKWISE = 2
WINDING_COUNTER_CLOCKWISE = 2

MESH_HEADER_SIZE = 12

##########


# QSSGRenderComponentType enum values
COMP_UINT8 = 1
COMP_UINT16 = 3
COMP_UINT32 = 5
COMP_UINT64 = 7
COMP_FLOAT32 = 10

LE = '<'   # all little-endian (x86/ARM default)

# Standard Qt Quick 3D vertex attribute names (must match exactly)
ATTR_POSITION = b"attr_pos"
ATTR_NORMAL = b"attr_norm"
ATTR_UV0 = b"attr_uv0"
ATTR_UV1 = b"attr_uv1"
ATTR_TANGENT = b"attr_textan"
ATTR_BINORMAL = b"attr_binormal"
ATTR_COLOR = b"attr_color"
ATTR_JOINTS = b"attr_joints"
ATTR_WEIGHTS = b"attr_weights"


# ══════════════════════════════════════════════════════════════════════════════
#  Qt .mesh format constants  (mirrors qssgmesh_p.h / qssgmesh.cpp)
# ══════════════════════════════════════════════════════════════════════════════

MULTI_HEADER_STRUCT_SIZE = 16
MULTI_ENTRY_STRUCT_SIZE = 16
MESH_HEADER_STRUCT_SIZE = 12
MESH_STRUCT_SIZE = 56
VERTEX_BUFFER_ENTRY_STRUCT_SIZE = 16
SUBSET_STRUCT_SIZE_V6 = 52

# _PAD4 = b"\x00\x00\x00\x00"
# ─────────────────────────────────────────────────────────────────
#  Low-level pack helpers
# ─────────────────────────────────────────────────────────────────


def _u32(v): return struct.pack(LE + 'I', int(v))
def _u16(v): return struct.pack(LE + 'H', int(v))
def _u64(v): return struct.pack(LE + 'Q', int(v))
def _f32(v): return struct.pack(LE + 'f', float(v))
def _utf16(s): return s.encode('utf-16le')


AXIS_FIX = Matrix((
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))


def blender_local_matrix(obj):
    if obj.parent:
        return obj.parent.matrix_world.inverted() @ obj.matrix_world
    return obj.matrix_world.copy()


def qt_local_matrix(obj, convert_coords=True):
    m = blender_local_matrix(obj)
    if convert_coords:
        m = AXIS_FIX @ m @ AXIS_FIX.inverted()
    return m


def qt_world_matrix(obj, convert_coords=True):
    m = obj.matrix_world.copy()
    if convert_coords:
        m = AXIS_FIX @ m @ AXIS_FIX.inverted()
    return m


def has_mirrored_handedness(obj, convert_coords=True):
    return qt_world_matrix(obj, convert_coords).to_3x3().determinant() < -1e-6


def _sign_component(value):
    return -1.0 if float(value) < 0.0 else 1.0


def qt_local_signed_scale(obj, convert_coords=True):
    scale = tuple(obj.scale)
    if convert_coords:
        return (scale[0], scale[2], scale[1])
    return scale


def qt_local_trs_(obj, convert_coords=True):
    m = qt_local_matrix(obj, convert_coords)

    loc, rot, scale = m.decompose()
    eul = rot.to_euler('XYZ')
    signed_scale = qt_local_signed_scale(obj, convert_coords)
    return (
        (loc.x, loc.y, loc.z),
        (math.degrees(eul.x), math.degrees(eul.y), math.degrees(eul.z)),
        (
            abs(scale.x) * _sign_component(signed_scale[0]),
            abs(scale.y) * _sign_component(signed_scale[1]),
            abs(scale.z) * _sign_component(signed_scale[2]),
        ),
    )


def qt_local_trs(obj, convert_coords=True):
    m = blender_local_matrix(obj)
    if convert_coords:
        m = AXIS_FIX @ m @ AXIS_FIX.inverted()

    loc, rot, scale = m.decompose()
    eul = rot.to_euler('XYZ')

    return (
        (loc.x, loc.y, loc.z),
        (math.degrees(eul.x), math.degrees(eul.y), math.degrees(eul.z)),
        (scale.x, scale.y, scale.z),
    )


#####
# ══════════════════════════════════════════════════════════════════════════════
#  OffsetTracker  (mirrors MeshInternal::MeshOffsetTracker)
# ══════════════════════════════════════════════════════════════════════════════
'''
class _OffsetTracker:
    def __init__(self):
        self.counter = 0

    def advance(self, n: int):
        self.counter += n

    def aligned_advance(self, n: int) -> int:
        self.counter += n
        pad = 4 - (self.counter % 4)
        self.counter += pad
        return pad


def _pad(n: int) -> bytes:
    return _PAD4[:n]
'''


# ─────────────────────────────────────────────────────────────────
#  Common helpers
# ─────────────────────────────────────────────────────────────────


def sanitize(name):
    s = re.sub(r'[^A-Za-z0-9_]', '_', name)
    return ('_' + s if s and s[0].isdigit() else s) or '_'


def qt_pos(value):
    """Blender Z-up → Qt Y-up coordinate conversion."""
    """Blender (X right, Y fwd, Z up)  →  Qt Quick 3D (X right, Y up, -Z fwd)"""

    value_ = tuple(value)
    return (value_[0], value_[2], -value_[1])


def qt_scale(value):
    value_ = tuple(value)
    return (value_[0], value_[2], value_[1])


def qt_rot(e): return (math.degrees(e.x),
                       math.degrees(e.z),
                       math.degrees(-e.y))


def inverse(t):
    return tuple(-1 * elem for elem in t)


# ─────────────────────────────────────────────────────────────────
#  PrincipledMaterial QML block
# ─────────────────────────────────────────────────────────────────

def mirror_info_for_obj(obj, convert_coords=True):
    signed_scale = qt_local_signed_scale(obj, convert_coords)
    scale_signs = tuple(_sign_component(v) for v in signed_scale)
    mirrored = has_mirrored_handedness(obj, convert_coords)

    # There is no universal way to infer a Blender object's UV unwrap axes from
    # object scale alone. This matches the common generated-mesh convention:
    # object X maps to U, the two remaining object axes contribute to V.
    uv_scale = (scale_signs[0], scale_signs[1] * scale_signs[2])
    uv_offset = (
        1.0 if uv_scale[0] < 0.0 else 0.0,
        1.0 if uv_scale[1] < 0.0 else 0.0,
    )
    has_negative = any(v < 0.0 for v in scale_signs)

    if not mirrored and not has_negative:
        return None

    return {
        "mirrored": mirrored,
        "signed_scale": signed_scale,
        "scale_signs": scale_signs,
        "uv_scale": uv_scale,
        "uv_offset": uv_offset,
    }


def mat_qml(mat, img_dir, exported_images, indent=1, material_id=None, mirror_info=None):
    return "\n".join(mat_to_quick3d(mat, img_dir, exported_images, indent, material_id, mirror_info))


def material_variant_suffix(mirror_info=None):
    if not mirror_info:
        return ""
    signs = "".join(
        "n" if v < 0.0 else "p" for v in mirror_info["scale_signs"])
    parity = "odd" if mirror_info["mirrored"] else "even"
    scale_digest = hashlib.sha1(
        ",".join(f"{v:.6g}" for v in mirror_info["signed_scale"]).encode(
            "utf-8")
    ).hexdigest()[:8]
    return f"_mirror_{signs}_{parity}_{scale_digest}"


'''
def material_id_for_name(name, mirror_info=None, material_lib=None):
    suffix = material_variant_suffix(mirror_info)
    id_ = f"mat_{sanitize(name)}{suffix}"
    if material_lib:
        id_+= f"_{sanitize(material_lib)}"

    return id_
'''

# ─────────────────────────────────────────────────────────────────
#  Light / Camera QML
# ─────────────────────────────────────────────────────────────────

_LIGHT_MAP = {'POINT': 'PointLight', 'SUN': 'DirectionalLight',
              'SPOT': 'SpotLight',   'AREA': 'AreaLight'}


def light_qml(obj, d=2, convert_coords=False):
    l = obj.data
    t = _LIGHT_MAP.get(l.type, 'PointLight')
    ind = "    " * d
    ind1 = "    " * (d+1)
    pos, rot, sc = qt_local_trs(obj, convert_coords)
    # pos = qt_pos(obj.location)
    # rot = qt_rot(obj.rotation_euler)
    col = l.color
    lines = [f"{ind}{t} {{",
             f'{ind1}objectName: "{obj.name}"',
             f"{ind1}position: Qt.vector3d{pos}",
             f"{ind1}scale: {sc}",
             f"{ind1}eulerRotation: Qt.vector3d{rot}",
             f"{ind1}color: Qt.rgba({col.r:.4f},{col.g:.4f},{col.b:.4f},1.0)",
             f"{ind1}brightness: {l.energy:.4f}"]
    if l.type == 'SPOT':
        lines += [f"{ind1}coneAngle: {math.degrees(l.spot_size):.4f}",
                  f"{ind1}innerConeAngle: {math.degrees(l.spot_size*(1-l.spot_blend)):.4f}"]
    if l.use_shadow:
        lines.append(f"{ind1}castsShadow: true")
    lines.append(f"{ind}}}")
    return "\n".join(lines)


def camera_qml(obj, d=2, convert_coords=False):
    cam = obj.data
    ind = "    " * d
    ind1 = "    " * (d+1)
    pos, rot, sc = qt_local_trs(obj, convert_coords)
    # pos = qt_pos(obj.location)
    # rot = qt_rot(obj.rotation_euler)
    if cam.type == 'ORTHO':
        lines = [f"{ind}OrthographicCamera {{",
                 f"{ind1}horizontalMagnification: {cam.ortho_scale:.4f}"]
    else:
        lines = [f"{ind}PerspectiveCamera {{",
                 f"{ind1}fieldOfView: {math.degrees(cam.angle):.4f}",
                 f"{ind1}fieldOfViewOrientation: PerspectiveCamera.Vertical"]
    lines += [f'{ind1}objectName: "{obj.name}"',
              f"{ind1}position: Qt.vector3d{pos}",
              f"{ind1}scale: {sc}",
              f"{ind1}eulerRotation: Qt.vector3d{rot}",
              f"{ind1}clipNear: {cam.clip_start:.4f}",
              f"{ind1}clipFar: {cam.clip_end:.4f}",
              f"{ind}}}"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  Animation → Timeline QML
# ─────────────────────────────────────────────────────────────────

def anim_qml(scene, node_ids, d=2):
    if not any(o.animation_data and o.animation_data.action
               for o in scene.objects):
        return ""

    fps = scene.render.fps
    s, e = scene.frame_start, scene.frame_end
    def I(n): return "    " * n
    lines = [f"{I(d)}Timeline {{",
             f"{I(d+1)}id: timeline",
             f"{I(d+1)}startFrame: {s}", f"{I(d+1)}endFrame: {e}",
             f"{I(d+1)}enabled: true",
             f"{I(d+1)}animations: [",
             f"{I(d+2)}TimelineAnimation {{",
             f"{I(d+3)}duration: {int((e-s)/fps*1000)}",
             f"{I(d+3)}from: {s}", f"{I(d+3)}to: {e}",
             f"{I(d+3)}running: true", f"{I(d+3)}loops: Animation.Infinite",
             f"{I(d+2)}}}", f"{I(d+1)}]", ""]

    prop_map = {
        'location':       ('position', lambda v: qt_pos(Vector(v))),
        'rotation_euler': ('eulerRotation', lambda v: qt_rot(Euler(v, 'XYZ'))),
        'scale':          ('scale', lambda v: qt_scale(Vector(v))),
    }

    for obj in scene.objects:
        if not (obj.animation_data and obj.animation_data.action):
            continue
        nid = node_ids.get(obj.name)
        if not nid:
            continue
        groups = {}
        for fc in obj.animation_data.action.fcurves:
            groups.setdefault(fc.data_path, {})[fc.array_index] = fc
        for dp, idx_map in groups.items():
            if dp not in prop_map:
                continue
            qt_prop, conv = prop_map[dp]
            frames = sorted(set(int(kp.co[0]) for fc in idx_map.values()
                                for kp in fc.keyframe_points))
            if not frames:
                continue
            lines += [f"{I(d+1)}KeyframeGroup {{",
                      f"{I(d+2)}target: {nid}",
                      f'{I(d+2)}property: "{qt_prop}"']
            for fr in frames:
                vals = [idx_map[ax].evaluate(fr) if ax in idx_map else 0.0
                        for ax in range(3)]
                qv = conv(vals)
                lines.append(f"{I(d+3)}Keyframe {{ frame: {fr}; "
                             f"value: Qt.vector3d({qv[0]:.4f},{qv[1]:.4f},{qv[2]:.4f}) }}")
            lines += [f"{I(d+1)}}}", ""]

    lines.append(f"{I(d)}}}")
    return "\n".join(lines)


def is_linked(obj):
    if obj is None:
        return False

    if obj.type in MESH_EXPORT_OBJECT_TYPES:
        return obj.library is not None or (obj.data and obj.data.library is not None)

    if obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION' and obj.instance_collection:
        return obj.library is not None or obj.instance_collection.library is not None

    return obj.library is not None


def hide_render(obj):
    has_renderable_collection = any(
        not col.hide_render
        for col in obj.users_collection
    )

    return (obj.hide_render and not is_linked(obj)) or not has_renderable_collection


def is_passive_rigid_body(obj):
    rigid_body = getattr(obj, "rigid_body", None)
    return rigid_body is not None and rigid_body.type == 'PASSIVE'


def is_identity_scale(value, epsilon=1.0e-6):
    if len(value) != 3:
        return False

    return all(abs(float(component) - 1.0) <= epsilon for component in value)


# ─────────────────────────────────────────────────────────────────
#  Main exporter
# ─────────────────────────────────────────────────────────────────

class BalsamExporter:
    def __init__(self, filepath, settings):
        self.root = Path(filepath).parent
        self.qml_path = Path(filepath)
        self.s = settings

        self.s.report({"INFO"}, f"Working directory: '{self.root}'")
        self.mesh_dir = self.root / "meshes"
        self.img_dir = self.root / "images"
        for d in (self.mesh_dir, self.img_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.exp_images = {}   # blender_name → "images/x.png"
        self.exp_materials = {}   # blender_name → (id_str, qml_str)
        self.exp_meshes = {}   # blender_name → "meshes/x.mesh"
        self.node_ids = {}   # blender_name → qml id
        self.uses_shipmate_material = False
        self.uses_physics = False

    def _mirror_key(self, mirror_info):
        if not mirror_info:
            return None
        return (
            mirror_info["mirrored"],
            tuple(mirror_info["signed_scale"]),
            tuple(mirror_info["uv_scale"]),
            tuple(mirror_info["uv_offset"]),
        )

    def _ensure_mat(self, mat, mirror_info=None):
        if not mat:
            return None

        material_id_ = material_id_for_name(mat)
        material_key = material_id_
        if material_key not in self.exp_materials:
            q = mat_qml(mat, self.img_dir, self.exp_images, indent=0,
                        material_id=material_id_, mirror_info=mirror_info)
            self.exp_materials[material_key] = (material_id_, q)
            if mirror_info:
                self.uses_shipmate_material = True

        return material_id_

    def extract_and_write_mesh(self, obj, filepath, lod_specs=None):
        lod_label = " with embedded LODs" if lod_specs else ""
        self.s.report(
            {"INFO"}, f"Exporting obj: '{obj.name}', mesh: '{obj.data.name}'{lod_label} → '{filepath}' …")
        # safe = sanitize(obj.data.name)

        try:
            mesh_data_ = extract_mesh_data(
                obj,
                apply_modifiers=self.s.apply_modifiers,
                convert_coords=self.s.convert_coords,
                lod_specs=lod_specs,
            )
        except Exception as exc:
            self.s.report({"ERROR"}, f"Failed to extract '{obj.name}': {exc}")
            return {'result': False}

        if mesh_data_["vertex_count"] == 0:
            self.s.report(
                {"WARNING"}, f"'{obj.name}' has no geometry; skipping.")
            return {'result': False}

        # mesh_name = bpy.path.clean_name(obj.name)
        write_mesh_file(mesh_data_, filepath)  # , subset_name=mesh_name)
        self.s.report({"INFO"}, f"{mesh_data_['vertex_count']} verts, "
                      f"{mesh_data_['index_count'] // 3} tris, entries: {len(mesh_data_['entries'])} → {filepath}"
                      )

        # validate_report_ = validate_qt_mesh(filepath)
        # self.s.report({"INFO"}, f'  Mesh validated: {validate_report_}')
        return {'material_names': mesh_data_['material_names'], 'result': True}
        # self.exp_meshes[obj.name]['material_names'] = mesh_data_['material_names']

    def _obj_qml(self, obj, d=2, offset=tuple((0, 0, 0))):
        # hide_render_ = hide_render(obj)

        cols_ = []
        for col in obj.users_collection:
            cols_.append(f'{col.name}: {col.hide_render}')

        # library_ = obj.library.name if obj.library else ''
        library_name_ = obj.data.library.name if obj.data and obj.data.library else ''
        data_name_ = obj.data.name if obj.data else ''
        self.s.report({"INFO"}, f"processing object: {obj.name}, type: {obj.type}, data_name: {data_name_}, instance_type: {obj.instance_type}, has_collection: {obj.instance_collection is not None}, offset: {offset}, cols: {cols_}, library: {library_name_}")

        # if hide_render_:
        #    return []

        blocks = []
        nid = f"node_{sanitize(obj.name)}"
        self.node_ids[obj.name] = nid
        def I(n): return "    " * n

        pos, rot, sc = qt_local_trs(obj, self.s.convert_coords)
        pos = tuple(map(sum, zip(pos, inverse(offset))))
        mirror_info = mirror_info_for_obj(obj, self.s.convert_coords)
        # pos = qt_pos(obj.location)
        # rot = qt_rot(obj.rotation_euler)
        # sc = qt_scale(obj.scale)

        if obj.type in MESH_EXPORT_OBJECT_TYPES:
            export_data_name_ = data_name_ if obj.type == 'MESH' else f"{obj.type}_{data_name_}"
            if obj.is_modified(bpy.context.scene, 'RENDER'):
                self.s.report(
                    {"WARNING"}, f"Geometry '{obj.data.name}' ({obj.name}, type: {obj.type}) has unapplied modifiers; exported geometry may not match viewport. Consider applying modifiers or enabling 'Apply Modifiers' option.")
                random_uuid_ = uuid.uuid4()
                short_hex_ = random_uuid_.hex[:6]
                # treat as separate mesh to avoid overwriting non-modifier version if both exist
                export_data_name_ += f'_{short_hex_}'

            mesh_key_ = f"{obj.type}/LOD/{library_name_}/{export_data_name_}" if self.s.generate_lods and library_name_ != '' else (
                f"{obj.type}/LOD/{export_data_name_}" if self.s.generate_lods else (
                    f"{obj.type}/{library_name_}/{export_data_name_}" if library_name_ != '' else f'{obj.type}/{export_data_name_}'
                )
            )

            self.s.report({"INFO"}, 'obj mesh key: ' + mesh_key_)
            if mesh_key_ not in self.exp_meshes:
                if library_name_ != '':
                    lib_dir = self.mesh_dir / library_name_
                    lib_dir.mkdir(parents=False, exist_ok=True)

                safe_data_name_ = sanitize(
                    f"{export_data_name_}_LODs" if self.s.generate_lods else export_data_name_)
                mp = self.mesh_dir / library_name_ / f"{safe_data_name_}.mesh"
                source_ = f"meshes/{library_name_}/{safe_data_name_}.mesh" if library_name_ != '' else f"meshes/{safe_data_name_}.mesh"
                result_ = self.extract_and_write_mesh(
                    obj, str(mp), LOD_LEVELS if self.s.generate_lods else None)
                if not result_['result']:
                    return blocks

                self.exp_meshes[mesh_key_] = {
                    'source': source_, 'material_names': result_['material_names']}

            rel = self.exp_meshes[mesh_key_]
            mat_ids_ = [mat_name_ for mat_name_ in rel['material_names']]

            for slot in obj.material_slots:
                if slot.material and material_id_for_name(slot.material) in mat_ids_:
                    self._ensure_mat(slot.material, mirror_info)

            # mat_ids = self.exp_meshes[obj.name]['material_names']

            is_static_rigid_body = is_passive_rigid_body(obj)
            model_indent = d + 1 if is_static_rigid_body else d
            model_lines = [f"{I(model_indent)}Model {{",
                     # f"{I(d+1)}id: {nid}",
                     f'{I(model_indent+1)}objectName: "{obj.name}"',
                     f'{I(model_indent+1)}source: "{rel["source"]}"',  # qrc:/{rel}
                     f"{I(model_indent+1)}position: Qt.vector3d{pos}",
                     f"{I(model_indent+1)}eulerRotation: Qt.vector3d{rot}",
                     f"{I(model_indent+1)}scale: Qt.vector3d{sc}"]
            if mirror_info:
                model_lines.append(
                    f"{I(model_indent+1)}property bool shipmateMirroredInstance: true")
                model_lines.append(
                    f"{I(model_indent+1)}property vector3d shipmateSignedScale: Qt.vector3d{mirror_info['signed_scale']}")
            if obj.hide_render:
                model_lines.append(f"{I(model_indent+1)}visible: false")
            if mat_ids_:
                model_lines.append(
                    f"{I(model_indent+1)}materials: [ {', '.join(mat_ids_)} ]")
            for child in obj.children:
                model_lines.extend(ln for ln in "\n".join(
                    self._obj_qml(child, model_indent + 1)).split("\n"))
            model_lines.append(f"{I(model_indent)}}}")

            if is_static_rigid_body:
                self.uses_physics = True
                lines = [f"{I(d)}StaticRigidBody {{"]
                lines.extend(model_lines)
                lines.extend([
                    f"{I(d+1)}collisionShapes: TriangleMeshShape {{",
                    f"{I(d+2)}enableDebugDraw: true",
                    f'{I(d+2)}source: "{rel["source"]}"',
                    f"{I(d+2)}position: Qt.vector3d{pos}",
                    f"{I(d+2)}eulerRotation: Qt.vector3d{rot}",
                ])
                if not is_identity_scale(sc):
                    lines.append(f"{I(d+2)}scale: Qt.vector3d{sc}")
                lines.extend([
                    f"{I(d+1)}}}",
                    f"{I(d)}}}",
                ])
            else:
                lines = model_lines

            blocks.append("\n".join(lines))

        elif obj.type == 'LIGHT' and self.s.export_lights:
            blocks.append(light_qml(obj, d, self.s.convert_coords))
        elif obj.type == 'CAMERA' and self.s.export_cameras:
            blocks.append(camera_qml(obj, d, self.s.convert_coords))
        elif obj.type == 'EMPTY':
            lines = export_shipmate(obj, nid, d)
            if len(lines) == 0:
                lines = [f"{I(d)}Node {{",
                         # f"{I(d+1)}id: {nid}",
                         f'{I(d+1)}objectName: "{obj.name}"',
                         f"{I(d+1)}position: Qt.vector3d{pos}",
                         f"{I(d+1)}eulerRotation: Qt.vector3d{rot}",
                         f"{I(d+1)}scale: Qt.vector3d{sc}"]

                for child in obj.children:
                    lines.extend(ln for ln in
                                 "\n".join(self._obj_qml(child, d + 1)).split("\n"))

                if obj.instance_type == "COLLECTION" and obj.instance_collection != None:
                    col_offs_ = qt_pos(obj.instance_collection.instance_offset)
                    for cobj in [o for o in obj.instance_collection.objects if o.parent is None]:
                        lines.extend(ln for ln in
                                     "\n".join(self._obj_qml(cobj, d + 1, col_offs_)).split("\n"))

                lines.append(f"{I(d)}}}")

            if len(lines) > 0:
                blocks.append("\n".join(lines))

        return blocks

    def process_collection(self, collection):
        objs_ = []
        node_blocks_ = []

        for child_ in collection.children:
            if not child_.hide_render:
                objs_.append(f'ch: {child_.name}')
                node_blocks_.extend(self.process_collection(child_))

        # self elements in collection
        for obj_ in collection.objects:
            if obj_.parent is None and not obj_.hide_render:
                objs_.append(f'{obj_.name}')
                node_blocks_.extend(self._obj_qml(obj_, d=2))

        self.s.report({"INFO"}, f'root objs: {objs_}')
        return node_blocks_

    def export(self):
        scene = bpy.context.scene
        stem = sanitize(self.qml_path.stem)

        # Process all top-level objects
        node_blocks = self.process_collection(scene.collection)

        # node_blocks = []
        # for obj in [o for o in scene.objects if o.parent is None]:
        #    node_blocks.extend(self._obj_qml(obj, d=2))

        # Animation
        anim = anim_qml(scene, self.node_ids,
                        d=2) if self.s.export_animations else ""

        # ── Assemble QML ──────────────────────────────────────────
        imports = ["import QtQuick", "import QtQuick3D"]
        if self.uses_physics:
            imports.append("import QtQuick3D.Physics")

        imports += ["", 'import LogicModule as LM']
        if self.s.export_animations:
            imports.append("import QtQuick.Timeline")

        mat_section = ""
        for name, (mid, mq) in self.exp_materials.items():
            reindented = "\n".join(("    " + l if l.strip() else l)
                                   for l in mq.split("\n"))
            mat_section += reindented + "\n\n"

        qml = f'// {stem}.qml\n' + '\n'.join(imports)
        qml += f"\n\n// Qt Quick 3D — exported by Blender Qt Balsam Exporter\n"
        qml += f"// Native .mesh files — no balsam conversion step required\n\n"
        qml += f"Node {{\n    id: root\n    objectName: '{stem}'"
        # if self.s.convert_coords:
        #    qml += f"\n    scale: Qt.vector3d(100., 100., 100.)"

        qml += "\n\n"
        if mat_section:
            qml += "    // ── Materials ─────────────────────────────────────────\n"
            qml += mat_section

        qml += "    // ── Scene Nodes ───────────────────────────────────────\n"
        qml += "    Node {\n"
        qml += "\n".join(node_blocks)
        qml += "\n    }\n"

        if anim:
            qml += "\n\n    // ── Animations ────────────────────────────────────\n"
            qml += anim

        qml += "\n}\n"

        self.qml_path.write_text(qml, encoding='utf-8')

        shipmate_material_files = []

        '''
        if self.uses_shipmate_material:
            addon_dir = Path(__file__).parent
            material_assets = (
                ("PrincipledBSDFMaterial.qml", addon_dir / "PrincipledBSDFMaterial.qml"),
                ("shaders/bsdf_principled.vert", addon_dir / "shaders" / "bsdf_principled.vert"),
                ("shaders/bsdf_principled.frag", addon_dir / "shaders" / "bsdf_principled.frag"),
            )
            for rel_name, src_path in material_assets:
                dest_path = self.root / rel_name
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src_path, dest_path)
                shipmate_material_files.append(rel_name)
        '''
        # ── .qrc ──────────────────────────────────────────────────
        meshes_sources_ = []
        for item in self.exp_meshes:
            meshes_sources_.append(self.exp_meshes[item]['source'])

        all_files = ([self.qml_path.name] +
                     list(meshes_sources_) +
                     list(self.exp_images.values()) +
                     shipmate_material_files)
        qrc = ['<RCC>', '    <qresource prefix="/">']
        for f in sorted(set(all_files)):
            qrc.append(f'        <file>{f}</file>')
        qrc += ['    </qresource>', '</RCC>']
        (self.root / f"{self.qml_path.stem}.qrc").write_text(
            "\n".join(qrc), encoding='utf-8')

        # ── CMake snippet ─────────────────────────────────────────
        cmake = [f"# No balsam step needed — .mesh files are already in Qt native format",
                 f"qt_add_resources(${{TARGET}} \"{stem}_assets\"",
                 f"    PREFIX \"/\"", f"    FILES"]
        for f in sorted(set(all_files)):
            cmake.append(f"        {f}")
        cmake.append(")")
        (self.root / "CMakeLists_qt3d_snippet.txt").write_text(
            "\n".join(cmake), encoding='utf-8')

        # ── Manifest ──────────────────────────────────────────────
        (self.root / "export_manifest.json").write_text(json.dumps({
            "scene": scene.name, "qml": self.qml_path.name,
            "meshes": meshes_sources_, "images": self.exp_images,
            "materials": [mid for mid, _ in self.exp_materials.values()],
        }, indent=2), encoding='utf-8')

        # {"CANCELLED"}
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────
#  Blender Operator & registration
# ─────────────────────────────────────────────────────────────────

class EXPORT_OT_qt_balsam(bpy.types.Operator):
    """Export Blender scene to Qt Quick 3D QML and native .mesh assets."""
    bl_idname = "export_scene.qt_balsam"
    bl_label = "Qt Quick 3D (.qml)"
    bl_options = {'PRESET', 'UNDO'}

    filepath:    bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.qml", options={'HIDDEN'})

    export_cameras: bpy.props.BoolProperty(
        name="Cameras", default=False,
        description="Export cameras as Qt camera nodes")
    export_lights: bpy.props.BoolProperty(
        name="Lights", default=False,
        description="Export lights as Qt light nodes")
    export_animations: bpy.props.BoolProperty(
        name="Animations", default=False,
        description="Export object animations via Timeline/KeyframeGroup")
    apply_modifiers: bpy.props.BoolProperty(
        name="Apply Modifiers", default=True,
        description="Apply mesh modifiers before exporting geometry")
    generate_lods: bpy.props.BoolProperty(
        name="Generate LODs", default=False,
        description="Embed LOD1-LOD3 index-only ranges using the original mesh vertices")
    selected_only: bpy.props.BoolProperty(
        name="Selected Only", default=False,
        description="Only export currently selected objects")
    convert_coords: bpy.props.BoolProperty(
        name="Convert Coordinates (Z-up → Y-up)",
        description="Convert Blender's Z-up to Qt Quick 3D's Y-up coordinate system",
        default=True,
    )
    filter_items: bpy.props.StringProperty()

    def execute(self, context):
        if not self.filepath.endswith(".qml"):
            self.filepath += ".qml"
        return BalsamExporter(self.filepath, self).export()

    def invoke(self, context, event):
        self.filepath = sanitize(context.scene.name) + ".qml"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        lo = self.layout
        lo.use_property_split = True
        lo.use_property_decorate = False
        b = lo.box()
        b.label(text="Include", icon='SCENE_DATA')
        b.prop(self, "export_cameras")
        b.prop(self, "export_lights")
        b.prop(self, "export_animations")
        b2 = lo.box()
        b2.label(text="Mesh", icon='MESH_DATA')
        b2.prop(self, "apply_modifiers")
        b2.prop(self, "generate_lods")
        b2.prop(self, "selected_only")
        b2.prop(self, "convert_coords")


class IMPORT_OT_qt_mesh(bpy.types.Operator, ImportHelper):
    """Import a Qt Quick 3D native .mesh file as Blender mesh geometry."""
    bl_idname = "import_scene.qt_quick3d_mesh"
    bl_label = "Qt Quick 3D Mesh (.mesh)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".mesh"
    filter_glob: bpy.props.StringProperty(default="*.mesh", options={'HIDDEN'})

    convert_coords: bpy.props.BoolProperty(
        name="Convert Coordinates (Y-up -> Z-up)",
        description="Convert Qt Quick 3D's Y-up coordinates back to Blender's Z-up coordinates",
        default=True,
    )
    import_normals: bpy.props.BoolProperty(
        name="Normals",
        description="Import attr_norm as custom split normals when present",
        default=True,
    )
    import_uvs: bpy.props.BoolProperty(
        name="UVs",
        description="Import attr_uv0 as a Blender UV map when present",
        default=True,
    )
    import_colors: bpy.props.BoolProperty(
        name="Vertex Colors",
        description="Import attr_color as a corner color attribute when present",
        default=True,
    )

    def execute(self, context):
        try:
            objects = import_qt_mesh_file(
                self.filepath,
                context=context,
                convert_coords=self.convert_coords,
                import_normals=self.import_normals,
                import_uvs=self.import_uvs,
                import_colors=self.import_colors,
            )
        except QtMeshImportError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import Qt .mesh: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Imported {len(objects)} Qt Quick 3D mesh object(s).")
        return {'FINISHED'}

    def draw(self, context):
        lo = self.layout
        lo.use_property_split = True
        lo.use_property_decorate = False
        b = lo.box()
        b.label(text="Geometry", icon='MESH_DATA')
        b.prop(self, "convert_coords")
        b.prop(self, "import_normals")
        b.prop(self, "import_uvs")
        b.prop(self, "import_colors")


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_qt_balsam.bl_idname,
                         text="Qt Quick 3D (.qml)")


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_qt_mesh.bl_idname,
                         text="Qt Quick 3D Mesh (.mesh)")


def register():
    bpy.utils.register_class(EXPORT_OT_qt_balsam)
    bpy.utils.register_class(IMPORT_OT_qt_mesh)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    shipmate_register()


def unregister():
    shipmate_unregister()

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(IMPORT_OT_qt_mesh)
    bpy.utils.unregister_class(EXPORT_OT_qt_balsam)


if __name__ == "__main__":
    register()
