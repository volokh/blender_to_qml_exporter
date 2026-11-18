"""
Qt Quick 3D native .mesh writer aimed at Qt 6.11 compatibility.

This writer keeps the v7 MeshDataHeader/container structure used by Qt Quick 3D,
but is stricter about subset offsets and payload layout than the older exporter.

Key choices:
- MeshDataHeader FILE_VERSION = 7
- MultiMeshInfo outer container with one mesh entry
- UTF-16LE string table without terminators
- subset.index_offset is written as INDEX ELEMENT OFFSET (not byte offset)
- lightmap width/height packed as two quint16 values
- optional subset LOD ranges are written into the v6+ LOD section
- target buffer descriptor present but empty

Binary format reverse-engineered from:
  qtquick3d/src/utils/qssgmesh_p.h   (v6.6, FILE_VERSION = 7)
  qtquick3d/src/utils/qssgmesh.cpp

File layout (all little-endian):
──────────────────────────────────────────────────────────────────
OUTER CONTAINER  (MultiMeshInfo)
  quint32  fileId       = 555777497   (0x2124_8959)
  quint32  fileVersion  = 1
  quint32  meshCount
  for each mesh:
    quint32  meshId
    quint64  byteOffset   (absolute, from start of file)

PER-MESH BLOCK  (MeshDataHeader + payload, 8-byte aligned)
  quint32  fileId       = 3365961549  (0xC884_094D)
  quint16  fileVersion  = 7
  quint16  flags        = 0
  quint32  sizeInBytes  (size of payload following this header)

  [payload – all offsets relative to start of payload]
  VertexBuffer:
    quint32  byteOffset    (into data section, 0 in v4+)
    quint32  byteSize
    quint32  stride
    quint32  entryCount
    for each entry:
      quint32  nameOffset   (into string table)
      quint32  nameLength
      quint32  componentType  (QSSGRenderComponentType enum)
      quint32  numComponents
      quint32  firstItemOffset  (byte offset inside one vertex)
      quint32  _pad

  IndexBuffer:
    quint32  componentType
    quint32  byteOffset    (0 in v4+)
    quint32  byteSize

  TargetBuffer (v7+):
    quint32  numTargets
    quint32  entryCount
    for each entry: same layout as VertexBufferEntry
    quint32  byteOffset
    quint32  byteSize

  SubsetCount: quint32
  for each subset:
    quint32  indexCount
    quint32  indexOffset
    float    boundsMin[3]
    float    boundsMax[3]
    quint16  lightmapWidth   (v5+)
    quint16  lightmapHeight  (v5+)
    quint32  lodCount        (v6+)
    for each lod (v6+):
      quint32  count; quint32  offset; float  distance

  Subset names (after all subset structs):
    for each subset: quint32 nameOffset, quint32 nameLength

  String table (UTF-16LE strings, no null terminator in qt6)

  TargetBuffer LOD data (v7+): not used here, 0 entries

  Actual binary vertex data   (padded to 4 bytes)
  Actual binary index data    (padded to 4 bytes)
  Actual target buffer data   (padded to 4 bytes)

NOTE: In practice the "offset" fields in the buffer descriptors are
all set to 0 in version 4+ (the loader ignores them), and the data
blobs are appended in order after the descriptor section.

This writer produces a single-mesh .mesh file (meshId = 1).
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from mathutils import Vector, Euler, Matrix
from pathlib import Path
import re
import json
import struct
import math
import bmesh
import bpy
import numpy as np

from .qt_simplifier import build_generated_lods, lod_normal_angles, triangles_from_flat
from .qt_lod_settings import active_lod_settings
from bpy.types import Operator
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty,
    FloatProperty, IntProperty
)

# QSSGRenderComponentType
MESH_FILE_ID = 3365961549
MESH_FILE_VERSION = 7
MESH_FLAGS = 0
MULTI_MESH_FILE_ID = 555777497    # MultiMeshInfo::FILE_ID
MULTI_MESH_FILE_VERSION = 1
MESH_DATA_FILE_ID = 3365961549   # MeshDataHeader::FILE_ID
# latest (supports morph split, LODs, lightmaps)
MESH_DATA_FILE_VERSION = 7

LOD_CAMERA_RANGES = (500.0, 2000.0, 5000.0, 10000.0, 20000.0, 50000.0, 100000.0)
LOD_REFERENCE_VERTICAL_FOV_DEGREES = 60.0
LOD_REFERENCE_VIEWPORT_HEIGHT = 1080.0

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
LOD_STRUCT_SIZE = 12

'''
def _u16(v: int) -> bytes:
    return struct.pack(LE + 'H', int(v))


def _u32(v: int) -> bytes:
    return struct.pack(LE + 'I', int(v))


def _u64(v: int) -> bytes:
    return struct.pack(LE + 'Q', int(v))


def _f32(v: float) -> bytes:
    return struct.pack(LE + 'f', float(v))


def _utf16(s: str) -> bytes:
    return s.encode('utf-16-le')


def _pad4(buf: bytearray) -> None:
    buf.extend(b'\x00' * ((-len(buf)) % 4))


@dataclass(frozen=True)
class VertexAttribute:
    name: str
    component_type: int
    num_components: int
    byte_offset: int


@dataclass(frozen=True)
class MeshSubset:
    name: str
    index_count: int
    index_offset: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    lightmap_width: int = 0
    lightmap_height: int = 0


class MeshWriterError(RuntimeError):
    pass


def _normalize_attributes(attributes):
    out = []
    for a in attributes:
        if isinstance(a, VertexAttribute):
            out.append(a)
        elif isinstance(a, tuple) and len(a) == 4:
            out.append(VertexAttribute(a[0], a[1], a[2], a[3]))
        else:
            raise MeshWriterError(f'invalid attribute descriptor: {a!r}')
    return out


def _normalize_subsets(subsets):
    out = []
    for s in subsets:
        if isinstance(s, MeshSubset):
            out.append(s)
        elif isinstance(s, tuple) and len(s) >= 5:
            out.append(MeshSubset(s[0], s[1], s[2], tuple(s[3]), tuple(s[4])))
        else:
            raise MeshWriterError(f'invalid subset descriptor: {s!r}')
    return out
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
    return (value_[0], value_[2], -value_[1])


def qt_rot(e): return (math.degrees(e.x),
                       math.degrees(e.z),
                       math.degrees(-e.y))


def inverse(t):
    return tuple(-1 * elem for elem in t)


'''
# ─────────────────────────────────────────────────────────────────
#  Blender mesh → Qt .mesh
# ─────────────────────────────────────────────────────────────────

class VertexEntry:
    def __init__(self, name, component_type, component_count, offset):
        self.name = name.encode('ascii')
        self.component_type = component_type
        self.component_count = component_count
        self.offset = offset


def align4(n):
    return (n + 3) & ~3


def pack_vertex_entries(entries):
    out = bytearray()
    for e in entries:
        out += struct.pack('<4I', 0, e.component_type,
                           e.component_count, e.offset)
    out += b'\x00' * (align4(len(out)) - len(out))
    return out


def pack_names(entries):
    out = bytearray()
    for e in entries:
        n = e.name + b'\x00'
        out += struct.pack('<I', len(n))
        out += n
        out += b'\x00' * (align4(4 + len(n)) - (4 + len(n)))
    return out
'''
# ══════════════════════════════════════════════════════════════════════════════
#  OffsetTracker  (mirrors MeshInternal::MeshOffsetTracker)
# ══════════════════════════════════════════════════════════════════════════════


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


_PAD4 = b"\x00\x00\x00\x00"


def _pad(n: int) -> bytes:
    return _PAD4[:n]


def material_id_for_name(mat):
    material_lib_ = mat.library.name if mat.library else None
    id_ = f"mat_{sanitize(mat.name)}"
    if material_lib_:
        id_ += f"_{sanitize(material_lib_)}"

    return id_

# ══════════════════════════════════════════════════════════════════════════════
#  Mesh geometry extraction from Blender
# ══════════════════════════════════════════════════════════════════════════════


def collect_mesh(obj, convert_coords, cloth_pin_group=None, export_tangents=False):  # , depsgraph, apply_modifiers=True):
    # eval_obj = obj.evaluated_get(depsgraph) if apply_modifiers else obj
    mesh = obj.to_mesh()
    if mesh is None:
        raise ValueError(f"Object '{obj.name}' of type '{obj.type}' did not produce mesh geometry")
    mesh.calc_loop_triangles()

    color_attr = None
    if hasattr(mesh, "color_attributes") and mesh.color_attributes:
        preferred = [a for a in mesh.color_attributes if getattr(
            a, "domain", None) == 'CORNER']
        color_attr = preferred[0] if preferred else mesh.color_attributes.active_color
        if color_attr and getattr(color_attr, "domain", None) != 'CORNER':
            color_attr = None
    elif hasattr(mesh, "vertex_colors") and mesh.vertex_colors:
        color_attr = mesh.vertex_colors[0]

    color_attr_name = color_attr.name if color_attr else None
    has_color = color_attr is not None
    active_uv_name = mesh.uv_layers.active.name if mesh.uv_layers.active else None
    uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active else None
    has_uv1 = len(mesh.uv_layers) > 1
    uv1_name = mesh.uv_layers[1].name if has_uv1 else None
    uv1_layer = mesh.uv_layers[1].data if has_uv1 else None
    col_layer = color_attr.data if color_attr else None
    has_tangent = export_tangents
    can_calc_blender_tangents = (
        has_tangent and active_uv_name is not None
        and all(len(poly.vertices) in (3, 4) for poly in mesh.polygons)
    )
    has_blender_tangent = can_calc_blender_tangents
    if has_blender_tangent:
        try:
            mesh.calc_tangents(uvmap=active_uv_name)
        except Exception:
            has_blender_tangent = False
        finally:
            active_layer = mesh.uv_layers.get(
                active_uv_name) if active_uv_name else None
            uv_layer = active_layer.data if active_layer else None
            uv1 = mesh.uv_layers.get(uv1_name) if uv1_name else None
            uv1_layer = uv1.data if uv1 else None
            has_uv1 = uv1_layer is not None
            if color_attr_name and hasattr(mesh, "color_attributes"):
                color_attr = mesh.color_attributes.get(color_attr_name)
            elif color_attr_name and hasattr(mesh, "vertex_colors"):
                color_attr = mesh.vertex_colors.get(color_attr_name)
            col_layer = color_attr.data if color_attr else None
            has_color = col_layer is not None

    uv_values = None
    if uv_layer:
        uv_values = []
        for item in uv_layer:
            uv = item.uv
            uv_values.append((float(uv[0]), float(uv[1])))

    uv1_values = None
    if uv1_layer:
        uv1_values = []
        for item in uv1_layer:
            uv = item.uv
            uv1_values.append((float(uv[0]), 1.0 - float(uv[1])))

    color_values = None
    if col_layer:
        color_values = []
        for item in col_layer:
            color = item.color
            if len(color) >= 4:
                color_values.append((float(color[0]), float(
                    color[1]), float(color[2]), float(color[3])))
            else:
                color_values.append(
                    (float(color[0]), float(color[1]), float(color[2]), 1.0))
    pin_group = obj.vertex_groups.get(cloth_pin_group) if cloth_pin_group else None
    has_cloth_pins = pin_group is not None
    has_color = color_values is not None or has_cloth_pins

    def fallback_tangent_basis(normal):
        n = Vector(normal)
        if n.length_squared == 0.0:
            n = Vector((0.0, 0.0, 1.0))
        n.normalize()
        reference = Vector((0.0, 0.0, 1.0))
        if abs(n.dot(reference)) > 0.95:
            reference = Vector((0.0, 1.0, 0.0))
        tangent = reference.cross(n)
        if tangent.length_squared == 0.0:
            tangent = Vector((1.0, 0.0, 0.0))
        tangent.normalize()
        binormal = n.cross(tangent)
        if binormal.length_squared == 0.0:
            binormal = Vector((0.0, 1.0, 0.0))
        binormal.normalize()
        return tuple(tangent), tuple(binormal)

    vbuf = bytearray()
    vmap = {}
    vertices = []
    indices = []
    bounds_min = [math.inf, math.inf, math.inf]
    bounds_max = [-math.inf, -math.inf, -math.inf]

    # ── Group faces by material index ─────────────────────────────
    mat_face_groups = {}
    for tris in mesh.loop_triangles:
        mat_face_groups.setdefault(tris.material_index, []).append(tris)

    subsets_data = []
    material_names = []
    material_slot_indices = []

    for mat_idx_ in sorted(mat_face_groups.keys()):
        polys = mat_face_groups[mat_idx_]
        subset_start = len(indices)
        bmin = [math.inf, math.inf, math.inf]
        bmax = [-math.inf, -math.inf, -math.inf]

        for tri in polys:
            tri_split_normals = getattr(tri, "split_normals", None)
            for corner, loop_index in enumerate(tri.loops):
                loop = mesh.loops[loop_index]
                vert = mesh.vertices[loop.vertex_index]
                pos = tuple(vert.co)
                norm = tuple(loop.normal)

                if tri_split_normals:
                    norm = tuple(tri_split_normals[corner])
                elif hasattr(loop, "normal"):
                    norm = tuple(loop.normal)
                else:
                    norm = tuple(vert.normal)

                uv = uv_values[loop_index] if uv_values else (0.0, 0.0)

                if has_tangent:
                    if has_blender_tangent:
                        tan = tuple(loop.tangent)
                        bitan = getattr(loop, "bitangent", None)
                        if bitan is None:
                            sign = getattr(loop, "bitangent_sign", 1.0)
                            bitan = Vector(norm).cross(Vector(tan)) * sign
                        binorm = tuple(bitan)
                    else:
                        tan, binorm = fallback_tangent_basis(norm)

                if convert_coords:
                    pos = qt_pos(pos)
                    norm = qt_pos(norm)
                    if has_tangent:
                        tan = qt_pos(tan)
                        binorm = qt_pos(binorm)

                vdata = pos + norm + uv

                if has_uv1:
                    uv1 = uv1_values[loop_index]
                    vdata += uv1

                if has_tangent:
                    vdata += tan + binorm

                if has_color:
                    col_ = color_values[loop_index] if color_values else (1.0, 1.0, 1.0, 1.0)
                    if has_cloth_pins:
                        weight = next((g.weight for g in vert.groups if g.group == pin_group.index), 0.0)
                        col_ = (*col_[:3], weight)
                    vdata += col_

                key = tuple(round(x, 6) for x in vdata)
                idx = vmap.get(key)
                if idx is None:
                    idx = len(vertices)
                    vmap[key] = idx

                    vbuf.extend(struct.pack("<3f", *pos))
                    vbuf.extend(struct.pack("<3f", *norm))

                    vbuf.extend(struct.pack("<2f", *uv))

                    if has_uv1:
                        vbuf.extend(struct.pack("<2f", *uv1))

                    if has_tangent:
                        vbuf.extend(struct.pack("<3f", *tan))
                        vbuf.extend(struct.pack("<3f", *binorm))

                    if has_color:
                        vbuf.extend(struct.pack("<4f", *col_))

                    vertices.append({
                        "pos": pos,
                        "norm": norm,
                        "uv": uv,
                    })

                    for i in range(3):
                        bounds_min[i] = min(bounds_min[i], pos[i])
                        bounds_max[i] = max(bounds_max[i], pos[i])

                indices.append(idx)
                for i in range(3):
                    bmin[i] = min(bmin[i], pos[i])
                    bmax[i] = max(bmax[i], pos[i])

        icount = len(indices) - subset_start
        if (icount == 0):
            continue

        mat = (obj.material_slots[mat_idx_].material if mat_idx_ < len(
            obj.material_slots) else None)
        if mat:
            material_names.append(material_id_for_name(mat))
        # Keep the subset's Blender slot index as the stable binding key.
        # Object-linked materials can differ even when the mesh datablock is shared.
        material_slot_indices.append(mat_idx_)

        sname = f"subset_{mat_idx_}"
        subsets_data.append({'sname': sname, 'icount': icount,
                            'subset_start': subset_start, 'bmin': tuple(bmin), 'bmax': tuple(bmax), 'mat_idx': mat_idx_})

    # material_name = mesh.materials[0].name if mesh.materials and mesh.materials[0] else ""
    has_uv0 = True
    has_normals = len(vertices) > 0

    return {'vertices': bytes(vbuf),
            'vertex_count': len(vertices),
            'indices': indices,
            'has_normals': has_normals,
            'has_uv0': has_uv0,
            'has_tangent': has_tangent,
            # 'bounds_min': tuple(bounds_min),
            # 'bounds_max': tuple(bounds_max),
            # 'material_name': material_name,
            'material_names': material_names,
            'material_slot_indices': material_slot_indices,
            'has_uv1': has_uv1,
            'has_color': has_color,
            'has_cloth_pins': has_cloth_pins,
            'subsets_data': subsets_data
            }


def _index_pack_format(indices):
    max_index = max(indices) if indices else 0
    if max_index <= 0xffff:
        return 'H', COMP_UINT16
    if max_index <= 0xffffffff:
        return 'I', COMP_UINT32
    return 'Q', COMP_UINT64


def _pack_indices(indices):
    idx_pref, idx_comp_type = _index_pack_format(indices)
    ibuf = bytearray()
    for idx in indices:
        ibuf.extend(struct.pack(f'<{idx_pref}', idx))
    return bytes(ibuf), idx_comp_type


def _attribute_offset(mesh, attr_name):
    entry = next((e for e in mesh["entries"] if e["name"] == attr_name), None)
    return entry["offset"] if entry is not None else None


def _attribute_array(mesh, attr_name, components):
    """Float values of one vertex attribute as an (N, components) float64 array, or None."""
    offset = _attribute_offset(mesh, attr_name)
    if offset is None:
        return None
    count = mesh["vertex_count"]
    raw = np.frombuffer(bytes(mesh["vbuf"]), dtype=np.uint8).reshape(count, mesh["stride"])
    values = raw[:, offset:offset + 4 * components].copy().view("<f4")
    return values.reshape(count, components).astype(np.float64)


def _split_vertex_bytes(mesh, normal_offset, new_vertices):
    """Copies of LOD0 vertices with replaced normals, as raw vertex-buffer bytes."""
    stride = mesh["stride"]
    source = bytes(mesh["vbuf"])
    out = bytearray()
    for src, normal in new_vertices:
        chunk = bytearray(source[src * stride:(src + 1) * stride])
        struct.pack_into("<3f", chunk, normal_offset, *normal)
        out.extend(chunk)
    return bytes(out)


def manual_lod_sources(obj):
    """
    Read manual LOD object choices from the enabled LOD panel.

    Returns (sources, problems): sources maps level -> Mesh or Object datablock,
    problems is a list of human-readable warnings for ignored properties.
    """
    sources = {}
    problems = []
    settings = active_lod_settings(obj)
    if settings is None:
        return sources, problems

    for level in range(1, len(LOD_CAMERA_RANGES) + 1):
        prop_name = f"LOD{level}"
        value = getattr(settings, f'lod{level}')
        if value is None:
            continue
        if value.type != 'MESH':
            problems.append(f"'{obj.name}': {prop_name} must be a mesh object; ignored")
            continue
        if value == obj or value.data == obj.data:
            problems.append(f"'{obj.name}': '{prop_name}' points to the object's own mesh; ignored")
            continue
        sources[level] = value
    return sources, problems


@contextmanager
def _lod_source_object(source):
    """Yield an object whose local-space geometry matches a manual LOD source."""
    if isinstance(source, bpy.types.Object):
        yield source
        return

    temp = bpy.data.objects.new(f"__qt_lod_tmp_{source.name}", source)
    bpy.context.scene.collection.objects.link(temp)
    try:
        bpy.context.view_layer.update()
        yield temp
    finally:
        bpy.data.objects.remove(temp, do_unlink=True)


def _camera_lod_distance(depth):
    """Qt LOD value for a camera-to-bounding-box surface depth."""
    return depth * 2.0 * math.tan(math.radians(LOD_REFERENCE_VERTICAL_FOV_DEGREES) * 0.5) / LOD_REFERENCE_VIEWPORT_HEIGHT


def custom_lod_distances_value(obj):
    """Enabled per-level camera-distance overrides, with None for global defaults."""
    settings = active_lod_settings(obj)
    if settings is None:
        return None
    values = [getattr(settings, f'distance{level}') if getattr(settings, f'use_distance{level}') else None
              for level in range(1, len(LOD_CAMERA_RANGES) + 1)]
    return values if any(value is not None for value in values) else None


def _custom_lod_distances(obj, warnings):
    """Enabled panel camera-to-bounds depths (LOD1, LOD2, ...), or None."""
    value = custom_lod_distances_value(obj)
    if value is None:
        return None
    try:
        distances = [float(d) if d is not None else None for d in value]
    except (TypeError, ValueError):
        warnings.append(f"'{obj.name}': LOD distance overrides must be numbers; ignored")
        return None
    if any(d is not None and (not math.isfinite(d) or d < 0.0) for d in distances):
        warnings.append(f"'{obj.name}': LOD distance overrides must be finite and non-negative; ignored")
        return None
    return distances


def _combine_lods(obj, apply_modifiers: bool, convert_coords: bool, manual_lods, generated_top=None,
                  lod_options=None, export_tangents=False):
    """
    Build the LOD levels of one mesh from hand-picked LOD meshes and generated LODs.

    Each entry of manual_lods is {"level", "source"}; its triangles are appended to
    LOD0's vertex buffer and keep their material subset. Generated levels come from
    the Qt port (see qt_simplifier) and fill every level without a manual mesh. Distances come
    from panel distance overrides when present, otherwise from the camera ranges or the
    automatic simplifier's geometric error.
    Levels are written from LOD1 up to the highest level in use, because the reader
    takes the level from the record's position. A level with nothing to show repeats
    the previous range. Distances never decrease. A manual mesh that is skipped falls
    back to the generated level if one exists. Warnings are returned in the
    'manual_lod_warnings' key.
    """
    base = extract_mesh_data(obj, apply_modifiers=apply_modifiers,
                             convert_coords=convert_coords, lod_specs=None, export_tangents=export_tangents)
    base_indices = list(base["indices"])
    base_points = _attribute_array(base, ATTR_POSITION, 3)
    combined_indices = list(base_indices)
    combined_vbuf = bytearray(base["vbuf"])
    vertex_total = base["vertex_count"]
    generated_specs = [{"level": level} for level in range(1, (generated_top or 0) + 1)]
    base_material_indices = {s["mat_idx"] for s in base["subsets_data"]}

    subsets = []
    for subset in base["subsets_data"]:
        copied = dict(subset)
        copied["lods"] = []
        subsets.append(copied)

    manual_by_level = {lod["level"]: lod for lod in manual_lods}
    generated_by_level = {spec["level"]: spec for spec in generated_specs or ()}

    warnings = []
    manual_geometry = {}
    for level in sorted(manual_by_level):
        lod = manual_by_level[level]
        source_name = lod["source"].name
        with _lod_source_object(lod["source"]) as source_obj:
            geometry = extract_mesh_data(source_obj, apply_modifiers=apply_modifiers,
                                         convert_coords=convert_coords, lod_specs=None,
                                         export_tangents=export_tangents)

        problem = None
        if geometry["vertex_count"] == 0:
            problem = "has no geometry"
        elif geometry["entries"] != base["entries"]:
            problem = "vertex attributes differ from LOD0 (UV2/tangents/colors must match)"
        if problem is not None:
            fallback = "generated LOD used instead" if level in generated_by_level else "skipped"
            warnings.append(f"LOD{level} '{source_name}' {problem}; {fallback}")
            continue

        lod_subsets = {s["mat_idx"]: s for s in geometry["subsets_data"]}
        unmatched = sorted(set(lod_subsets) - base_material_indices)
        if unmatched:
            warnings.append(f"LOD{level} '{source_name}' has material slots {unmatched} "
                            f"unused by LOD0; those triangles are dropped")
        manual_geometry[level] = (geometry, lod_subsets)

    # level -> one (global flat indices, distance) entry per subset
    level_data = {}
    for level in sorted(manual_geometry):
        geometry, lod_subsets = manual_geometry[level]
        vertex_base = vertex_total
        combined_vbuf.extend(geometry["vbuf"])
        vertex_total += geometry["vertex_count"]
        per_subset = []
        for subset in subsets:
            source_subset = lod_subsets.get(subset["mat_idx"])
            if source_subset is None:
                per_subset.append(None)
                continue
            start = source_subset["subset_start"]
            lod_tris = triangles_from_flat(geometry["indices"][start:start + source_subset["icount"]])
            local = [i for tri in lod_tris for i in tri]
            per_subset.append(([i + vertex_base for i in local], 0.0))
        level_data[level] = per_subset

    distance_scale = float((lod_options or {}).get("distance_scale", 1.0))
    custom = _custom_lod_distances(obj, warnings) if (lod_options or {}).get("custom_distances") else None
    camera_ranges = (lod_options or {}).get("camera_ranges", True)
    generated = {}
    if generated_specs:
        angles = lod_normal_angles(lod_options)
        normals = _attribute_array(base, ATTR_NORMAL, 3)
        ranges = [(s["subset_start"], s["icount"]) for s in subsets]
        generated, new_vertices = build_generated_lods(
            base_points, normals, ranges, base_indices, generated_top, vertex_total, angles,
            capped=bool((lod_options or {}).get("vertex_caps")), warnings=warnings)
        level_data.update({level: entries for level, entries in generated.items() if level not in manual_geometry})
        if new_vertices:
            normal_offset = _attribute_offset(base, ATTR_NORMAL)
            combined_vbuf.extend(_split_vertex_bytes(base, normal_offset, new_vertices))
            vertex_total += len(new_vertices)

    if not camera_ranges and manual_geometry and max(manual_geometry) > (generated_top or 0):
        angles = lod_normal_angles(lod_options)
        normals = _attribute_array(base, ATTR_NORMAL, 3)
        ranges = [(s["subset_start"], s["icount"]) for s in subsets]
        generated, _ = build_generated_lods(
            base_points, normals, ranges, base_indices, max(manual_geometry), base["vertex_count"], angles,
            capped=bool((lod_options or {}).get("vertex_caps")), warnings=warnings)

    for per_subset in level_data.values():
        for index, entry in enumerate(per_subset):
            if entry is not None and not entry[0]:
                per_subset[index] = None

    largest_subset = max(range(len(subsets)), key=lambda index: subsets[index]["icount"], default=None)
    camera_depths = []
    if camera_ranges:
        for index in range(max(level_data, default=0)):
            depth = (custom[index] if custom is not None and index < len(custom) and custom[index] is not None
                     else LOD_CAMERA_RANGES[index])
            if camera_depths and depth < camera_depths[-1]:
                warnings.append(f"LOD{index + 1} camera distance {depth:g} is less than the previous "
                                f"LOD distance; clamped to {camera_depths[-1]:g}")
                depth = camera_depths[-1]
            camera_depths.append(depth)
    for index, subset in enumerate(subsets):
        for level, per_subset in level_data.items():
            if per_subset[index] is None:
                continue
            ids, value = per_subset[index]
            if camera_ranges:
                distance = _camera_lod_distance(camera_depths[level - 1])
            elif custom is not None and level <= len(custom) and custom[level - 1] is not None:
                distance = _camera_lod_distance(custom[level - 1])
            elif level in manual_geometry:
                generated_entries = generated.get(level)
                reference = generated_entries[index] if generated_entries is not None else None
                if reference is None and generated_entries is not None and largest_subset is not None:
                    reference = generated_entries[largest_subset]
                if reference is None:
                    distance = _camera_lod_distance(LOD_CAMERA_RANGES[level - 1])
                    warnings.append(f"{subset['sname']}: LOD{level} has no automatic simplification "
                                    "distance; using the camera range instead")
                else:
                    distance = reference[1]
            else:
                distance = value
            per_subset[index] = (ids, distance / distance_scale)

    tails = [max((level for level, per_subset in level_data.items() if per_subset[index] is not None), default=0)
             for index in range(len(subsets))]
    last_level = max(level_data, default=0)
    for level in range(1, last_level + 1):
        per_subset = level_data.get(level)
        for index, subset in enumerate(subsets):
            lods = subset["lods"]
            previous = lods[-1] if lods else None
            entry = per_subset[index] if per_subset is not None else None
            if entry is None:
                if level > tails[index]:
                    continue
                # Nothing for this subset at this level: repeat the previous range (LOD0 for LOD1) so the
                # reader's record position still lines up with the level number. Its distance
                # is the next real level's, so Qt never picks the repeat before that level is due.
                nxt = min((k for k in level_data if k > level and level_data[k][index] is not None), default=None)
                fill = float(level_data[nxt][index][1]) if nxt is not None else 0.0
                fill = max(fill, previous["distance"] if previous is not None else 0.0)
                if previous is not None:
                    source_range = {"count": previous["count"], "offset": previous["offset"]}
                else:
                    source_range = {"count": subset["icount"], "offset": subset["subset_start"]}
                lods.append({**source_range, "distance": fill})
                continue

            lod_ids, distance = entry
            if custom is not None and previous is not None and distance < previous["distance"]:
                warnings.append(f"{subset['sname']}: LOD{level} distance is less than the preceding "
                                "LOD; clamped to the preceding distance")
            distance = max(float(distance), previous["distance"] if previous is not None else 0.0)
            offset = 0
            if lod_ids:
                offset = len(combined_indices)
                combined_indices.extend(lod_ids)
            lods.append({"count": len(lod_ids), "offset": offset, "distance": distance})

    ibuf, idx_comp_type = _pack_indices(combined_indices)
    base["vbuf"] = bytes(combined_vbuf)
    base["vertex_count"] = vertex_total
    base["ibuf"] = ibuf
    base["index_type"] = idx_comp_type
    base["index_count"] = len(combined_indices)
    base["indices"] = combined_indices
    base["subsets_data"] = subsets
    base["manual_lod_levels"] = sorted(manual_geometry)
    base["manual_lod_warnings"] = warnings
    return base


def extract_mesh_data(obj, apply_modifiers: bool, convert_coords: bool, lod_specs=None, manual_lods=None,
                      lod_options=None, export_tangents=False) -> dict:
    """
    Triangulate the mesh and build vertex / index buffers.

    lod_specs and manual_lods select embedded LOD levels (see _combine_lods).
    lod_options holds the LOD normal recalculation settings.

    Returns a dict with keys:
        entries, stride, vbuf, ibuf, index_type, index_count, vertex_count
    """
    if manual_lods or lod_specs:
        return _combine_lods(obj, apply_modifiers, convert_coords, manual_lods or (), lod_specs, lod_options,
                             export_tangents)

    # ── Get evaluated (modifier-applied) or raw mesh ──────────────────────
    depsgraph = bpy.context.evaluated_depsgraph_get()
    use_evaluated_object = apply_modifiers or obj.type != 'MESH'
    eval_obj = obj.evaluated_get(depsgraph) if use_evaluated_object else obj

    cloth = next((m for m in getattr(obj, 'modifiers', ()) if m.type == 'CLOTH' and m.show_render), None)
    pin_group = cloth.settings.vertex_group_mass if cloth else None
    mesh_ = collect_mesh(eval_obj, convert_coords, pin_group, export_tangents)
    '''
    if apply_modifiers:
        eval_obj = obj.evaluated_get(depsgraph)
        me = eval_obj.to_mesh()
    else:
        me = obj.to_mesh()
    '''
    '''
    me = eval_obj.to_mesh()

    # ── Triangulate via bmesh ─────────────────────────────────────────────
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])

    uv_layer = bm.loops.layers.uv.active
    has_uvs = uv_layer is not None
    has_norms = True  # Blender always has normals after calc_normals_split()

    # me.calc_normals_split()
    # Build a map from loop to split normal
    split_normals = {}
    for poly in me.polygons:
        for li in poly.loop_indices:
            loop = me.loops[li]
            split_normals[loop.index] = tuple(loop.normal)
    '''
    # ── Compute attribute offsets ─────────────────────────────────────────
    entries = []
    offset = 0

    def add_attr(name, ncomp):
        nonlocal offset
        entries.append({"name": name, "type": COMP_FLOAT32,
                       "count": ncomp, "offset": offset})
        # entries.append((name, COMP_FLOAT32, ncomp, offset))
        offset += ncomp * 4

    add_attr(ATTR_POSITION, 3)
    add_attr(ATTR_NORMAL,   3)

    has_uv = mesh_['has_uv0']
    if has_uv:
        add_attr(ATTR_UV0, 2)

    has_uv1 = mesh_['has_uv1']
    if has_uv1:
        add_attr(ATTR_UV1, 2)

    has_tangent = mesh_['has_tangent']
    if has_tangent:
        add_attr(ATTR_TANGENT, 3)
        add_attr(ATTR_BINORMAL, 3)

    has_color = mesh_['has_color']
    if has_color:
        add_attr(ATTR_COLOR, 4)

    indices_ = mesh_['indices']
    idx_count_ = len(indices_)
    ibuf, idx_comp_type_ = _pack_indices(indices_)

    # ── Cleanup ───────────────────────────────────────────────────────────
    if use_evaluated_object:
        eval_obj.to_mesh_clear()
    else:
        obj.to_mesh_clear()

    return {
        "entries":      entries,
        "stride":       offset,
        "vbuf":         mesh_['vertices'],
        "ibuf":         ibuf,
        "index_type":   idx_comp_type_,
        "index_count":  idx_count_,
        "vertex_count": mesh_['vertex_count'],
        'indices':      indices_,
        'subsets_data': mesh_['subsets_data'],
        'material_names': mesh_['material_names'],
        'material_slot_indices': mesh_.get('material_slot_indices', []),
        'has_cloth_pins': mesh_.get('has_cloth_pins', False),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  .mesh file writer  (mirrors MeshInternal::writeMeshData + Mesh::save)
# ══════════════════════════════════════════════════════════════════════════════

def transform_collision_mesh(mesh, linear):
    """Bake a Qt-space linear transform into an independent collision mesh.

    Extract without LODs. Rebuild a position-only buffer, preserve material subset
    ranges, update bounds, and reverse winding for odd reflections. Never mutate
    the visual mesh or Blender's datablocks.
    """
    from mathutils import Vector
    if abs(linear.determinant()) < 1e-12:
        raise ValueError("Cannot export a collision mesh with a singular transform")
    position = next(e for e in mesh['entries'] if e['name'] == ATTR_POSITION)
    points = [linear @ Vector(struct.unpack_from('<3f', mesh['vbuf'],
              i * mesh['stride'] + position['offset'])) for i in range(mesh['vertex_count'])]
    indices = list(mesh['indices'])
    if linear.determinant() < 0.0:
        for i in range(0, len(indices), 3):
            indices[i + 1], indices[i + 2] = indices[i + 2], indices[i + 1]
    subsets = []
    for original in mesh['subsets_data']:
        subset = dict(original)
        used = [points[indices[i]] for i in range(subset['subset_start'],
                subset['subset_start'] + subset['icount'])]
        if used:
            subset['bmin'] = tuple(min(p[k] for p in used) for k in range(3))
            subset['bmax'] = tuple(max(p[k] for p in used) for k in range(3))
        subset.pop('lods', None)
        subsets.append(subset)
    result = dict(mesh)
    result.update(entries=[{'name': ATTR_POSITION, 'type': COMP_FLOAT32, 'count': 3, 'offset': 0}],
                  stride=12, vbuf=b''.join(struct.pack('<3f', *p) for p in points),
                  indices=indices, subsets_data=subsets)
    result['ibuf'], result['index_type'] = _pack_indices(indices)
    return result


def _write_mesh_body(mesh: dict) -> bytes:
    # buf = bytearray()
    tracker = _OffsetTracker()

    entries = mesh["entries"]
    vbuf = mesh["vbuf"]
    ibuf = mesh["ibuf"]
    stride = mesh["stride"]
    index_type = mesh["index_type"]
    index_count = mesh["index_count"]
    subsetsData_ = mesh['subsets_data']

    # n_vb = len(entries)
    vsize = len(vbuf)
    isize = len(ibuf)

    # MESH_STRUCT (56 bytes)
    body = bytearray()
    targetEntries_ = []
    targetData_ = []
    targetCount_ = 0
    subsetsCount_ = len(subsetsData_)
    body.extend(struct.pack('<4I', len(targetEntries_),
                len(entries), stride, len(targetData_)))
    body.extend(struct.pack('<4I', vsize, index_type, 0, isize))
    # targetCount, subsetsCount, legacy joints
    body.extend(struct.pack('<4I', targetCount_, subsetsCount_, 0, 0))
    body.extend(struct.pack('<2I', DRAW_MODE_TRIANGLES,
                WINDING_COUNTER_CLOCKWISE))

    # def wu32(v): body.extend(struct.pack("<I", v))
    # def wf32(v): body.extend(struct.pack("<f", v))

    tracker.advance(MESH_STRUCT_SIZE)

    # VB entry structs
    eb_size = 0
    for e in entries:
        body.extend(struct.pack("<4I", 0, e["type"], e["count"], e["offset"]))
        eb_size += VERTEX_BUFFER_ENTRY_STRUCT_SIZE

    body.extend(_pad(tracker.aligned_advance(eb_size)))

    # VB entry names
    for e in entries:
        entryName_ = e["name"] + b"\x00"
        body.extend(struct.pack("<I", len(entryName_)))
        body.extend(entryName_)
        body.extend(_pad(tracker.aligned_advance(4 + len(entryName_))))

    # Vertex buffer
    body.extend(vbuf)
    body.extend(_pad(tracker.aligned_advance(vsize)))

    # Index buffer
    body.extend(ibuf)
    body.extend(_pad(tracker.aligned_advance(isize)))

    # Subset struct V6 (52 bytes)
    subsetByteSize_ = 0
    for item in subsetsData_:
        subsetCount_ = item['icount']
        subsetOffset_ = item['subset_start']
        subsetName_ = item['sname']
        lightmapSizeHintWidth_ = 0
        lightmapSizeHintHeight_ = 0
        lodCount_ = len(item.get('lods', []))
        body.extend(struct.pack('<2I', subsetCount_, subsetOffset_))
        body.extend(struct.pack('<3f', *item['bmin']))
        body.extend(struct.pack('<3f', *item['bmax']))
        body.extend(struct.pack('<5I', 0, len(subsetName_) + 1,
                                lightmapSizeHintWidth_, lightmapSizeHintHeight_, lodCount_))
        subsetByteSize_ += SUBSET_STRUCT_SIZE_V6

    body.extend(_pad(tracker.aligned_advance(subsetByteSize_)))

    # Subset name (UTF-16-LE)
    for item in subsetsData_:
        subsetName_ = item['sname']
        name_utf16_ = (subsetName_ + "\x00").encode("utf-16le")
        body.extend(name_utf16_)
        body.extend(_pad(tracker.aligned_advance(len(name_utf16_))))

    # LOD data
    lodByteSize_ = 0
    for item in subsetsData_:
        for lod in item.get('lods', []):
            body.extend(struct.pack(
                '<2If',
                int(lod['count']),
                int(lod['offset']),
                float(lod['distance']),
            ))
            lodByteSize_ += LOD_STRUCT_SIZE
    body.extend(_pad(tracker.aligned_advance(lodByteSize_)))

    # Data for morphTargets

    return bytes(body)


def write_mesh_file(mesh: dict, out_path: str):
    """Write a complete Qt .mesh file."""
    body = _write_mesh_body(mesh)
    file_buf = bytearray()

    # Mesh data header (12 bytes)
    file_buf.extend(struct.pack("<IHHI", MESH_FILE_ID,
                    MESH_FILE_VERSION, 0, len(body)))
    file_buf.extend(body)

    # Multi-mesh entry (16 bytes)
    multi_offset = len(file_buf)
    # mesh data at offset 0, mesh id = 1, padding
    file_buf.extend(struct.pack("<QII", 0, 1, 0))

    # Multi-mesh footer (16 bytes)
    file_buf.extend(struct.pack("<4I", MULTI_MESH_FILE_ID,
                    MULTI_MESH_FILE_VERSION, multi_offset, 1))   # meshCount

    with open(out_path, "wb") as fh:
        fh.write(file_buf)
