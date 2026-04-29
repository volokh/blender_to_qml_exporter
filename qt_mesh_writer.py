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


def collect_mesh(obj, convert_coords):  # , depsgraph, apply_modifiers=True):
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
    has_tangent = True
    can_calc_blender_tangents = (
        active_uv_name is not None
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
    has_color = color_values is not None

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
                    col_ = color_values[loop_index]
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
            'has_uv1': has_uv1,
            'has_color': has_color,
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


def _sample_lod_triangle_indices(indices, ratio):
    tri_count = len(indices) // 3
    if tri_count <= 0:
        return []

    clamped_ratio = max(0.01, min(1.0, float(ratio)))
    target_count = max(1, int(round(tri_count * clamped_ratio)))
    if target_count >= tri_count:
        return list(indices[:tri_count * 3])

    selected = []
    used = set()
    if target_count == 1:
        selected = [tri_count // 2]
    else:
        for step in range(target_count):
            tri_idx = int(round(step * (tri_count - 1) / (target_count - 1)))
            while tri_idx in used and tri_idx + 1 < tri_count:
                tri_idx += 1
            while tri_idx in used and tri_idx - 1 >= 0:
                tri_idx -= 1
            if tri_idx in used:
                continue
            used.add(tri_idx)
            selected.append(tri_idx)

    sampled = []
    for tri_idx in selected:
        start = tri_idx * 3
        sampled.extend(indices[start:start + 3])
    return sampled


def _combine_mesh_lods(obj, apply_modifiers: bool, convert_coords: bool, lod_specs) -> dict:
    base = extract_mesh_data(
        obj,
        apply_modifiers=apply_modifiers,
        convert_coords=convert_coords,
        lod_specs=None,
    )

    base_indices = list(base["indices"])
    combined_indices = list(base["indices"])
    subsets = []
    for subset in base["subsets_data"]:
        copied = dict(subset)
        copied["lods"] = []
        subsets.append(copied)

    for spec in lod_specs:
        distance = float(spec["distance"])
        ratio = spec.get("ratio")

        if ratio is None:
            for subset in subsets:
                subset["lods"].append({
                    "count": 0,
                    "offset": 0,
                    "distance": distance,
                })
            continue

        for subset in subsets:
            start = subset["subset_start"]
            end = start + subset["icount"]
            lod_indices = _sample_lod_triangle_indices(base_indices[start:end], ratio)
            offset = len(combined_indices)
            combined_indices.extend(lod_indices)
            subset["lods"].append({
                "count": len(lod_indices),
                "offset": offset if lod_indices else 0,
                "distance": distance,
            })

    ibuf, idx_comp_type = _pack_indices(combined_indices)
    base["ibuf"] = ibuf
    base["index_type"] = idx_comp_type
    base["index_count"] = len(combined_indices)
    base["indices"] = combined_indices
    base["subsets_data"] = subsets
    return base


def extract_mesh_data(obj, apply_modifiers: bool, convert_coords: bool, lod_specs=None) -> dict:
    """
    Triangulate the mesh and build vertex / index buffers.

    Returns a dict with keys:
        entries, stride, vbuf, ibuf, index_type, index_count, vertex_count
    """
    if lod_specs:
        return _combine_mesh_lods(obj, apply_modifiers, convert_coords, lod_specs)

    # ── Get evaluated (modifier-applied) or raw mesh ──────────────────────
    depsgraph = bpy.context.evaluated_depsgraph_get()
    use_evaluated_object = apply_modifiers or obj.type != 'MESH'
    eval_obj = obj.evaluated_get(depsgraph) if use_evaluated_object else obj

    mesh_ = collect_mesh(eval_obj, convert_coords)
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
    }


# ══════════════════════════════════════════════════════════════════════════════
#  .mesh file writer  (mirrors MeshInternal::writeMeshData + Mesh::save)
# ══════════════════════════════════════════════════════════════════════════════

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
