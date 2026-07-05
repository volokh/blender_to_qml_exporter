"""
Qt Quick 3D native .mesh importer for Blender.

The parser mirrors Qt Quick 3D's private QSSGMesh reader:
  qtquick3d/src/utils/qssgmesh_p.h
  qtquick3d/src/utils/qssgmesh.cpp

It supports mesh data versions 3 through 7. The Blender importer consumes the
base vertex/index/subset geometry and skips morph target buffers.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


MULTI_MESH_FILE_ID = 555777497
MULTI_MESH_FILE_VERSION = 1
MESH_FILE_ID = 3365961549
LEGACY_MESH_FILE_VERSION = 3
MESH_FILE_VERSION = 7

MULTI_HEADER_STRUCT_SIZE = 16
MULTI_ENTRY_STRUCT_SIZE = 16
MESH_HEADER_STRUCT_SIZE = 12
MESH_STRUCT_SIZE = 56
VERTEX_BUFFER_ENTRY_STRUCT_SIZE = 16
SUBSET_STRUCT_SIZE_V3_V4 = 40
SUBSET_STRUCT_SIZE_V5 = 48
SUBSET_STRUCT_SIZE_V6 = 52
LOD_STRUCT_SIZE = 12

DRAW_MODE_POINTS = 1
DRAW_MODE_LINE_STRIP = 2
DRAW_MODE_LINE_LOOP = 3
DRAW_MODE_LINES = 4
DRAW_MODE_TRIANGLE_STRIP = 5
DRAW_MODE_TRIANGLE_FAN = 6
DRAW_MODE_TRIANGLES = 7

WINDING_CLOCKWISE = 1
WINDING_COUNTER_CLOCKWISE = 2

COMPONENT_TYPE_UNSIGNED_INT8 = 1
COMPONENT_TYPE_INT8 = 2
COMPONENT_TYPE_UNSIGNED_INT16 = 3
COMPONENT_TYPE_INT16 = 4
COMPONENT_TYPE_UNSIGNED_INT32 = 5
COMPONENT_TYPE_INT32 = 6
COMPONENT_TYPE_UNSIGNED_INT64 = 7
COMPONENT_TYPE_INT64 = 8
COMPONENT_TYPE_FLOAT16 = 9
COMPONENT_TYPE_FLOAT32 = 10
COMPONENT_TYPE_FLOAT64 = 11

ATTR_POSITION = "attr_pos"
ATTR_NORMAL = "attr_norm"
ATTR_UV0 = "attr_uv0"
ATTR_UV1 = "attr_uv1"
ATTR_COLOR = "attr_color"

_COMPONENT_FORMATS = {
    COMPONENT_TYPE_UNSIGNED_INT8: "B",
    COMPONENT_TYPE_INT8: "b",
    COMPONENT_TYPE_UNSIGNED_INT16: "H",
    COMPONENT_TYPE_INT16: "h",
    COMPONENT_TYPE_UNSIGNED_INT32: "I",
    COMPONENT_TYPE_INT32: "i",
    COMPONENT_TYPE_UNSIGNED_INT64: "Q",
    COMPONENT_TYPE_INT64: "q",
    COMPONENT_TYPE_FLOAT16: "e",
    COMPONENT_TYPE_FLOAT32: "f",
    COMPONENT_TYPE_FLOAT64: "d",
}


class QtMeshImportError(RuntimeError):
    pass


@dataclass
class QtVertexEntry:
    name: str
    component_type: int
    component_count: int
    offset: int


@dataclass
class QtLod:
    count: int
    offset: int
    distance: float


@dataclass
class QtSubset:
    name: str
    count: int
    offset: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    lightmap_width: int = 0
    lightmap_height: int = 0
    name_length: int = 0
    lod_count: int = 0
    lods: list[QtLod] = field(default_factory=list)


@dataclass
class QtMeshData:
    mesh_id: int
    mesh_offset: int
    file_version: int
    flags: int
    size_in_bytes: int
    stride: int
    draw_mode: int
    winding: int
    vertex_entries: list[QtVertexEntry]
    vertex_buffer: bytes
    index_component_type: int
    index_buffer: bytes
    target_count: int
    target_entries_count: int
    target_data_size: int
    subsets: list[QtSubset]

    @property
    def vertex_count(self) -> int:
        if self.stride <= 0:
            return 0
        return len(self.vertex_buffer) // self.stride


class _MeshCursor:
    def __init__(self, start_offset: int):
        self.start_offset = start_offset
        self.byte_counter = 0

    @property
    def offset(self) -> int:
        return self.start_offset + self.byte_counter

    def advance(self, size: int) -> None:
        self.byte_counter += int(size)

    def aligned_advance(self, size: int) -> int:
        self.advance(size)
        pad = 4 - (self.byte_counter % 4)
        self.byte_counter += pad
        return pad


def _ensure_available(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise QtMeshImportError(f"Unexpected end of file while reading {label}.")


def _unpack_from(fmt: str, data: bytes, offset: int, label: str):
    size = struct.calcsize(fmt)
    _ensure_available(data, offset, size, label)
    return struct.unpack_from(fmt, data, offset)


def _decode_ascii_name(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _decode_utf16_name(raw: bytes) -> str:
    if not raw:
        return ""
    return raw.decode("utf-16le", errors="replace").split("\x00", 1)[0]


def _component_size(component_type: int) -> int:
    fmt = _COMPONENT_FORMATS.get(component_type)
    if fmt is None:
        raise QtMeshImportError(f"Unsupported Qt mesh component type: {component_type}.")
    return struct.calcsize("<" + fmt)


def _read_components(buffer: bytes, base_offset: int, component_type: int, component_count: int) -> tuple:
    fmt = _COMPONENT_FORMATS.get(component_type)
    if fmt is None:
        raise QtMeshImportError(f"Unsupported Qt mesh component type: {component_type}.")
    size = struct.calcsize("<" + fmt) * component_count
    _ensure_available(buffer, base_offset, size, "vertex attribute")
    return struct.unpack_from("<" + (fmt * component_count), buffer, base_offset)


def _read_index_buffer(mesh: QtMeshData) -> list[int]:
    fmt = _COMPONENT_FORMATS.get(mesh.index_component_type)
    if fmt is None:
        raise QtMeshImportError(f"Unsupported Qt index component type: {mesh.index_component_type}.")

    item_size = _component_size(mesh.index_component_type)
    count = len(mesh.index_buffer) // item_size
    if count == 0:
        return []

    return [item[0] for item in struct.iter_unpack("<" + fmt, mesh.index_buffer[:count * item_size])]


def _read_file_header(data: bytes) -> list[tuple[int, int]]:
    if len(data) < MULTI_HEADER_STRUCT_SIZE + MULTI_ENTRY_STRUCT_SIZE:
        raise QtMeshImportError("File is too small to be a Qt Quick 3D .mesh file.")

    footer_offset = len(data) - MULTI_HEADER_STRUCT_SIZE
    file_id, file_version, _entries_offset, mesh_count = _unpack_from(
        "<4I", data, footer_offset, "multi-mesh footer")

    if file_id != MULTI_MESH_FILE_ID or file_version != MULTI_MESH_FILE_VERSION:
        raise QtMeshImportError("Invalid Qt Quick 3D multi-mesh footer.")
    if mesh_count < 1:
        raise QtMeshImportError("Qt .mesh file contains no mesh entries.")

    entries_offset = footer_offset - (MULTI_ENTRY_STRUCT_SIZE * mesh_count)
    _ensure_available(data, entries_offset, MULTI_ENTRY_STRUCT_SIZE * mesh_count, "multi-mesh entries")

    entries = []
    for index in range(mesh_count):
        mesh_offset, mesh_id, _padding = _unpack_from(
            "<QII",
            data,
            entries_offset + index * MULTI_ENTRY_STRUCT_SIZE,
            "multi-mesh entry",
        )
        entries.append((int(mesh_id), int(mesh_offset)))
    return entries


def _read_mesh_data(data: bytes, mesh_id: int, mesh_offset: int) -> QtMeshData:
    file_id, file_version, flags, size_in_bytes = _unpack_from(
        "<IHHI", data, mesh_offset, "mesh data header")

    if file_id != MESH_FILE_ID:
        raise QtMeshImportError(f"Invalid mesh data id for mesh {mesh_id}: {file_id}.")
    if file_version < LEGACY_MESH_FILE_VERSION or file_version > MESH_FILE_VERSION:
        raise QtMeshImportError(f"Unsupported Qt mesh data version: {file_version}.")

    cursor = _MeshCursor(mesh_offset + MESH_HEADER_STRUCT_SIZE)
    (
        target_entries_count,
        vertex_entries_count,
        stride,
        target_data_size,
        vertex_data_size,
        index_component_type,
        _legacy_index_offset,
        index_data_size,
        target_count,
        subset_count,
        _joints_offset,
        _joints_count,
        draw_mode,
        winding,
    ) = _unpack_from("<14I", data, cursor.offset, "mesh descriptor")
    cursor.advance(MESH_STRUCT_SIZE)

    if file_version < 7:
        target_entries_count = 0
        target_data_size = 0

    vertex_entries = []
    for index in range(vertex_entries_count):
        _name_offset, component_type, component_count, entry_offset = _unpack_from(
            "<4I",
            data,
            cursor.offset + index * VERTEX_BUFFER_ENTRY_STRUCT_SIZE,
            "vertex buffer entry",
        )
        vertex_entries.append(QtVertexEntry("", component_type, component_count, entry_offset))
    cursor.aligned_advance(vertex_entries_count * VERTEX_BUFFER_ENTRY_STRUCT_SIZE)

    for entry in vertex_entries:
        (name_length,) = _unpack_from("<I", data, cursor.offset, "vertex attribute name length")
        cursor.advance(4)
        _ensure_available(data, cursor.offset, name_length, "vertex attribute name")
        entry.name = _decode_ascii_name(data[cursor.offset:cursor.offset + name_length])
        cursor.aligned_advance(name_length)

    _ensure_available(data, cursor.offset, vertex_data_size, "vertex buffer")
    vertex_buffer = data[cursor.offset:cursor.offset + vertex_data_size]
    cursor.aligned_advance(vertex_data_size)

    _ensure_available(data, cursor.offset, index_data_size, "index buffer")
    index_buffer = data[cursor.offset:cursor.offset + index_data_size]
    cursor.aligned_advance(index_data_size)

    subsets = []
    subset_struct_size = SUBSET_STRUCT_SIZE_V3_V4
    if file_version >= 6:
        subset_struct_size = SUBSET_STRUCT_SIZE_V6
    elif file_version >= 5:
        subset_struct_size = SUBSET_STRUCT_SIZE_V5

    for index in range(subset_count):
        subset_offset = cursor.offset + index * subset_struct_size
        (
            count,
            offset,
            min_x,
            min_y,
            min_z,
            max_x,
            max_y,
            max_z,
            _name_offset,
            name_length,
        ) = _unpack_from("<II6fII", data, subset_offset, "subset")

        lightmap_width = 0
        lightmap_height = 0
        lod_count = 0
        if file_version >= 5:
            lightmap_width, lightmap_height = _unpack_from(
                "<2I", data, subset_offset + SUBSET_STRUCT_SIZE_V3_V4, "subset lightmap hint")
        if file_version >= 6:
            (lod_count,) = _unpack_from(
                "<I", data, subset_offset + SUBSET_STRUCT_SIZE_V5, "subset lod count")

        subsets.append(QtSubset(
            name="",
            count=count,
            offset=offset,
            bounds_min=(min_x, min_y, min_z),
            bounds_max=(max_x, max_y, max_z),
            lightmap_width=lightmap_width,
            lightmap_height=lightmap_height,
            name_length=name_length,
            lod_count=lod_count,
        ))
    cursor.aligned_advance(subset_count * subset_struct_size)

    for subset in subsets:
        # Qt stores UTF-16 code units including a trailing NUL. The field is
        # named nameLength in code, but it is a character count, not bytes.
        name_byte_size = subset.name_length * 2
        _ensure_available(data, cursor.offset, name_byte_size, "subset name")
        subset.name = _decode_utf16_name(data[cursor.offset:cursor.offset + name_byte_size])
        cursor.aligned_advance(name_byte_size)

    lod_byte_size = 0
    lod_offset = cursor.offset
    for subset in subsets:
        for index in range(subset.lod_count):
            count, offset, distance = _unpack_from(
                "<2If", data, lod_offset + lod_byte_size, "subset lod")
            subset.lods.append(QtLod(count, offset, distance))
            lod_byte_size += LOD_STRUCT_SIZE
    cursor.aligned_advance(lod_byte_size)

    return QtMeshData(
        mesh_id=mesh_id,
        mesh_offset=mesh_offset,
        file_version=file_version,
        flags=flags,
        size_in_bytes=size_in_bytes,
        stride=stride,
        draw_mode=draw_mode,
        winding=winding,
        vertex_entries=vertex_entries,
        vertex_buffer=vertex_buffer,
        index_component_type=index_component_type,
        index_buffer=index_buffer,
        target_count=target_count,
        target_entries_count=target_entries_count,
        target_data_size=target_data_size,
        subsets=subsets,
    )


def read_qt_mesh_file(filepath: str | Path) -> list[QtMeshData]:
    path = Path(filepath)
    data = path.read_bytes()
    return [_read_mesh_data(data, mesh_id, mesh_offset)
            for mesh_id, mesh_offset in _read_file_header(data)]


def _attribute_map(mesh: QtMeshData) -> dict[str, QtVertexEntry]:
    attributes = {}
    for entry in mesh.vertex_entries:
        attributes.setdefault(entry.name, entry)
    return attributes


def _read_vertex_attribute(mesh: QtMeshData, entry: QtVertexEntry, vertex_index: int) -> tuple:
    base_offset = vertex_index * mesh.stride + entry.offset
    return _read_components(
        mesh.vertex_buffer,
        base_offset,
        entry.component_type,
        entry.component_count,
    )


def _qt_to_blender_vec3(value: tuple, convert_coords: bool) -> tuple[float, float, float]:
    x, y, z = float(value[0]), float(value[1]), float(value[2])
    if not convert_coords:
        return (x, y, z)
    return (x, -z, y)


def _normalize_vec3(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2])
    if length <= 1.0e-8:
        return (0.0, 0.0, 1.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _valid_face(face: tuple[int, ...], vertex_count: int) -> bool:
    return len(face) >= 3 and len(set(face)) == len(face) and all(0 <= item < vertex_count for item in face)


def _valid_edge(edge: tuple[int, int], vertex_count: int) -> bool:
    return edge[0] != edge[1] and all(0 <= item < vertex_count for item in edge)


def _append_topology(indices: list[int], draw_mode: int, winding: int, vertex_count: int,
                     faces: list[tuple[int, ...]], edges: list[tuple[int, int]],
                     face_materials: list[int], material_index: int) -> None:
    reverse_winding = winding == WINDING_CLOCKWISE

    def add_face(face):
        if reverse_winding:
            face = tuple(reversed(face))
        if _valid_face(face, vertex_count):
            faces.append(tuple(face))
            face_materials.append(material_index)

    if draw_mode == DRAW_MODE_TRIANGLES:
        for offset in range(0, len(indices) - 2, 3):
            add_face((indices[offset], indices[offset + 1], indices[offset + 2]))
    elif draw_mode == DRAW_MODE_TRIANGLE_STRIP:
        for offset in range(0, len(indices) - 2):
            if offset % 2:
                face = (indices[offset + 1], indices[offset], indices[offset + 2])
            else:
                face = (indices[offset], indices[offset + 1], indices[offset + 2])
            add_face(face)
    elif draw_mode == DRAW_MODE_TRIANGLE_FAN:
        if len(indices) >= 3:
            center = indices[0]
            for offset in range(1, len(indices) - 1):
                add_face((center, indices[offset], indices[offset + 1]))
    elif draw_mode == DRAW_MODE_LINES:
        for offset in range(0, len(indices) - 1, 2):
            edge = (indices[offset], indices[offset + 1])
            if _valid_edge(edge, vertex_count):
                edges.append(edge)
    elif draw_mode == DRAW_MODE_LINE_STRIP:
        for offset in range(0, len(indices) - 1):
            edge = (indices[offset], indices[offset + 1])
            if _valid_edge(edge, vertex_count):
                edges.append(edge)
    elif draw_mode == DRAW_MODE_LINE_LOOP:
        for offset in range(0, len(indices) - 1):
            edge = (indices[offset], indices[offset + 1])
            if _valid_edge(edge, vertex_count):
                edges.append(edge)
        if len(indices) > 2:
            edge = (indices[-1], indices[0])
            if _valid_edge(edge, vertex_count):
                edges.append(edge)
    elif draw_mode == DRAW_MODE_POINTS:
        return
    else:
        raise QtMeshImportError(f"Unsupported Qt mesh draw mode: {draw_mode}.")


def _geometry_ranges(mesh: QtMeshData, indices: list[int]) -> list[tuple[int, int, int]]:
    ranges = []
    for subset_index, subset in enumerate(mesh.subsets):
        if subset.count <= 0:
            continue
        start = max(0, min(int(subset.offset), len(indices)))
        end = max(start, min(start + int(subset.count), len(indices)))
        if end > start:
            ranges.append((start, end, subset_index))
    if not ranges:
        ranges.append((0, len(indices), -1))
    return ranges


def _make_material(name: str, index: int):
    import bpy

    mat = bpy.data.materials.new(name or f"subset_{index}")
    hue = (index * 0.173) % 1.0
    mat.diffuse_color = (
        0.45 + 0.35 * math.sin((hue + 0.00) * math.tau) ** 2,
        0.45 + 0.35 * math.sin((hue + 0.33) * math.tau) ** 2,
        0.45 + 0.35 * math.sin((hue + 0.66) * math.tau) ** 2,
        1.0,
    )
    return mat


def _apply_uv_layer(blender_mesh, qt_mesh: QtMeshData, attributes: dict[str, QtVertexEntry]) -> None:
    uv_entry = attributes.get(ATTR_UV0)
    if uv_entry is None or uv_entry.component_count < 2:
        return

    uv_layer = blender_mesh.uv_layers.new(name="UVMap")
    for polygon in blender_mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = blender_mesh.loops[loop_index].vertex_index
            uv = _read_vertex_attribute(qt_mesh, uv_entry, vertex_index)
            uv_layer.data[loop_index].uv = (float(uv[0]), float(uv[1]))


def _apply_color_layer(blender_mesh, qt_mesh: QtMeshData, attributes: dict[str, QtVertexEntry]) -> None:
    color_entry = attributes.get(ATTR_COLOR)
    if color_entry is None or color_entry.component_count < 3:
        return

    try:
        color_layer = blender_mesh.color_attributes.new(
            name="QtColor",
            type='FLOAT_COLOR',
            domain='CORNER',
        )
    except Exception:
        color_layer = blender_mesh.vertex_colors.new(name="QtColor")

    for polygon in blender_mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = blender_mesh.loops[loop_index].vertex_index
            color = _read_vertex_attribute(qt_mesh, color_entry, vertex_index)
            alpha = float(color[3]) if color_entry.component_count >= 4 else 1.0
            color_layer.data[loop_index].color = (
                float(color[0]),
                float(color[1]),
                float(color[2]),
                alpha,
            )


def _apply_custom_normals(blender_mesh, qt_mesh: QtMeshData, attributes: dict[str, QtVertexEntry],
                          convert_coords: bool) -> None:
    normal_entry = attributes.get(ATTR_NORMAL)
    if normal_entry is None or normal_entry.component_count < 3:
        return
    if not hasattr(blender_mesh, "normals_split_custom_set"):
        return

    normals = []
    for polygon in blender_mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = blender_mesh.loops[loop_index].vertex_index
            normal = _read_vertex_attribute(qt_mesh, normal_entry, vertex_index)
            normals.append(_normalize_vec3(_qt_to_blender_vec3(normal, convert_coords)))

    try:
        blender_mesh.normals_split_custom_set(normals)
        if hasattr(blender_mesh, "use_auto_smooth"):
            blender_mesh.use_auto_smooth = True
    except Exception:
        return


def _create_blender_object(qt_mesh: QtMeshData, name: str, context, convert_coords: bool,
                           import_normals: bool, import_uvs: bool, import_colors: bool):
    import bpy

    attributes = _attribute_map(qt_mesh)
    position_entry = attributes.get(ATTR_POSITION)
    if position_entry is None or position_entry.component_count < 3:
        raise QtMeshImportError(f"Mesh {qt_mesh.mesh_id} does not contain attr_pos geometry.")

    vertices = []
    for vertex_index in range(qt_mesh.vertex_count):
        pos = _read_vertex_attribute(qt_mesh, position_entry, vertex_index)
        vertices.append(_qt_to_blender_vec3(pos, convert_coords))

    indices = _read_index_buffer(qt_mesh)
    faces = []
    edges = []
    face_materials = []
    for start, end, material_index in _geometry_ranges(qt_mesh, indices):
        _append_topology(
            indices[start:end],
            qt_mesh.draw_mode,
            qt_mesh.winding,
            len(vertices),
            faces,
            edges,
            face_materials,
            material_index,
        )

    mesh_name = f"{name}Mesh"
    blender_mesh = bpy.data.meshes.new(mesh_name)
    blender_mesh.from_pydata(vertices, edges, faces)
    blender_mesh.validate(clean_customdata=False)
    blender_mesh.update()

    for index, subset in enumerate(qt_mesh.subsets):
        blender_mesh.materials.append(_make_material(subset.name or f"subset_{index}", index))

    if blender_mesh.materials:
        for polygon, material_index in zip(blender_mesh.polygons, face_materials):
            if 0 <= material_index < len(blender_mesh.materials):
                polygon.material_index = material_index

    if import_uvs:
        _apply_uv_layer(blender_mesh, qt_mesh, attributes)
    if import_colors:
        _apply_color_layer(blender_mesh, qt_mesh, attributes)
    if import_normals:
        _apply_custom_normals(blender_mesh, qt_mesh, attributes, convert_coords)
    blender_mesh.update()

    obj = bpy.data.objects.new(name, blender_mesh)
    target_collection = context.collection if context is not None else bpy.context.collection
    target_collection.objects.link(obj)
    return obj


def import_qt_mesh_file(filepath: str | Path, context=None, convert_coords: bool = True,
                        import_normals: bool = True, import_uvs: bool = True,
                        import_colors: bool = True) -> list:
    import bpy

    path = Path(filepath)
    meshes = read_qt_mesh_file(path)
    objects = []
    base_name = path.stem
    for qt_mesh in meshes:
        object_name = base_name if len(meshes) == 1 else f"{base_name}_{qt_mesh.mesh_id}"
        objects.append(_create_blender_object(
            qt_mesh,
            object_name,
            context,
            convert_coords,
            import_normals,
            import_uvs,
            import_colors,
        ))

    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    return objects
