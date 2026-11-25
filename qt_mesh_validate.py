#!/usr/bin/env python3
import argparse
import json
import struct

MULTI_FILE_ID = 555777497
MESH_FILE_ID = 3365961549
FILE_VERSION = 1

VERTEX_BUFFER_ENTRY_STRUCT_SIZE = 16
MULTI_HEADER_STRUCT_SIZE = 16
MULTI_ENTRY_STRUCT_SIZE = 16
MESH_HEADER_STRUCT_SIZE = 12
MESH_STRUCT_SIZE = 56
SUBSET_STRUCT_SIZE_V6 = 52
LOD_STRUCT_SIZE = 12
# QSSGRenderComponentType values for index buffers
_INDEX_FORMATS = {1: 'B', 3: 'H', 5: 'I', 7: 'Q'}


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

    def offset(self):
        return self.counter


_PAD4 = b"\x00\x00\x00\x00"


def _pad(n: int) -> bytes:
    return _PAD4[:n]


def align4(n):
    return (n + 3) & ~3


def read_u32(buf, off):
    return struct.unpack_from('<I', buf, off)[0]


def read_u16(buf, off):
    return struct.unpack_from('<H', buf, off)[0]


def read_mesh(data, mesh_id, mesh_offset):
    # mesh_offset, mesh_id, _ = struct.unpack_from('<QII', data, len(data) - 32)
    mesh_file_id, mesh_file_version, mesh_flags, mesh_size = struct.unpack_from(
        '<IHHI', data, mesh_offset)
    if mesh_file_id != MESH_FILE_ID:
        raise ValueError(f'invalid mesh file id: {mesh_file_id}')

    tracker = _OffsetTracker()
    tracker.advance(mesh_offset + MESH_HEADER_STRUCT_SIZE)

    target_entries, vertex_entries, stride, target_data_size, vertex_data_size, \
        index_component_type, _legacy_index_offset, index_data_size, target_count, \
        subset_count, _joints_offset, _joints_count, draw_mode, winding \
        = struct.unpack_from('<14I', data, tracker.offset())
    tracker.advance(MESH_STRUCT_SIZE)

    entries = []
    entriesByteSize_ = 0
    for _ in range(vertex_entries):
        _name_offs, ctype, ccount, eoffs = struct.unpack_from(
            '<4I', data, entriesByteSize_ + tracker.offset())
        entries.append(
            {'componentType': ctype, 'componentCount': ccount, 'offset': eoffs})
        entriesByteSize_ += VERTEX_BUFFER_ENTRY_STRUCT_SIZE

    tracker.aligned_advance(entriesByteSize_)
    # print(f'tracker: {tracker.offset()} , off: {off}')

    for i in range(vertex_entries):
        name_len = read_u32(data, tracker.offset())
        tracker.advance(4)  # sizeof(quint32)
        off_ = tracker.offset()
        namez = data[off_:off_ + name_len]
        tracker.aligned_advance(name_len)
        entries[i]['name'] = namez[:-
                                   1].decode('ascii', errors='replace') if name_len else ''
        print(f'idx: {i} len: {name_len}, name: {entries[i]["name"]}')

    vertex_data_offset = tracker.offset()
    tracker.aligned_advance(vertex_data_size)
    index_data_offset = tracker.offset()
    tracker.aligned_advance(index_data_size)

    subsets = []
    subsetByteSize_ = 0
    for _ in range(subset_count):
        count, idx_off, minx, miny, minz, maxx, maxy, maxz, _name_off, name_len, lm_w, lm_h, lod_count = struct.unpack_from(
            '<II6fIIIII', data, subsetByteSize_ + tracker.offset())
        subsets.append({'count': count, 'offset': idx_off, 'boundsMin': [minx, miny, minz], 'boundsMax': [
                       maxx, maxy, maxz], 'nameLength': name_len, 'lightmap': [lm_w, lm_h], 'lodCount': lod_count})
        subsetByteSize_ += SUBSET_STRUCT_SIZE_V6

    tracker.aligned_advance(subsetByteSize_)

    for s in subsets:
        name_bytes = s['nameLength'] * 2
        off_ = tracker.offset()
        raw = data[off_:off_ + name_bytes]
        tracker.aligned_advance(name_bytes)
        # off = mesh_offset + 12 + align4(off - (mesh_offset + 12))
        s['name'] = raw[:-2].decode('utf-16le',
                                    errors='replace') if name_bytes >= 2 else ''

    # LOD section (v6+): written after subset names, one 12-byte record per subset LOD
    lod_byte_size = 0
    lod_base = tracker.offset()
    for s in subsets:
        s['lods'] = []
        for _ in range(s['lodCount']):
            count, offset, distance = struct.unpack_from(
                '<2If', data, lod_base + lod_byte_size)
            s['lods'].append(
                {'count': count, 'offset': offset, 'distance': distance})
            lod_byte_size += LOD_STRUCT_SIZE
    tracker.aligned_advance(lod_byte_size)

    index_elements = _read_index_buffer(
        data, index_data_offset, index_data_size, index_component_type)
    vertex_count = vertex_data_size // stride if stride else 0
    lod_summary = _summarize_lods(subsets, index_elements)
    for subset in subsets:
        subset['levels'] = _summarize_subset_lods(subset, index_elements)

    return {
        'meshId': mesh_id, 'meshOffset': mesh_offset,
        'meshHeader': {'fileId': mesh_file_id, 'fileVersion': mesh_file_version, 'flags': mesh_flags, 'sizeInBytes': mesh_size},
        'mesh': {'vertexEntries': vertex_entries, 'targetEntries': target_entries, 'stride': stride, 'vertexDataSize': vertex_data_size,
                 'indexComponentType': index_component_type, 'indexDataSize': index_data_size, 'targetCount': target_count, 'subsetCount': subset_count,
                 'drawMode': draw_mode, 'winding': winding, 'vertexDataOffset': vertex_data_offset, 'indexDataOffset': index_data_offset},
        'attributes': entries,
        'subsets': subsets,
        'vertexBufferVertices': vertex_count,
        'lods': lod_summary,
    }


def _read_index_buffer(data, offset, size, component_type):
    fmt = _INDEX_FORMATS.get(component_type)
    if fmt is None:
        raise ValueError(f'unsupported index component type: {component_type}')
    count = size // struct.calcsize('<' + fmt)
    return list(struct.unpack_from(f'<{count}{fmt}', data, offset))


def _summarize_lods(subsets, index_elements):
    """
    Level 0 is the main mesh (subset index ranges). Level N uses each subset's N-th
    LOD range, or its last available range if it has fewer levels. A level's vertex
    count is the number of distinct vertices its index ranges reference.
    """
    level_count = max((len(s['lods']) for s in subsets), default=0)
    summary = []
    for level in range(level_count + 1):
        ranges = []
        distance = None
        for s in subsets:
            if level == 0 or not s['lods']:
                ranges.append((s['offset'], s['count']))
            else:
                lod = s['lods'][min(level, len(s['lods'])) - 1]
                ranges.append((lod['offset'], lod['count']))
                if level <= len(s['lods']) and distance is None:
                    distance = lod['distance']

        used = set()
        index_count = 0
        for offset, count in ranges:
            if count == 0:
                continue
            if offset + count > len(index_elements):
                raise ValueError(f'LOD{level} index range {offset}+{count} exceeds index buffer '
                                 f'({len(index_elements)} indices)')
            used.update(index_elements[offset:offset + count])
            index_count += count

        summary.append({
            'level': level,
            'distance': distance,
            'vertices': len(used),
            'triangles': index_count // 3,
            'indexCount': index_count,
        })
    return summary


def _summarize_subset_lods(subset, index_elements):
    """LOD levels of one subset, LOD0 first; each level is its own index range."""
    levels = [_level_stats(
        0, [(subset['offset'], subset['count'])], None, index_elements)]
    for number, lod in enumerate(subset['lods'], start=1):
        levels.append(_level_stats(
            number, [(lod['offset'], lod['count'])], lod['distance'], index_elements))
    return levels


def _level_stats(level, ranges, distance, index_elements):
    used = set()
    index_count = 0
    for offset, count in ranges:
        if count == 0:
            continue
        if offset + count > len(index_elements):
            raise ValueError(f'LOD{level} index range {offset}+{count} exceeds index buffer '
                             f'({len(index_elements)} indices)')
        used.update(index_elements[offset:offset + count])
        index_count += count
    return {'level': level, 'distance': distance, 'vertices': len(used),
            'triangles': index_count // 3, 'indexCount': index_count}


def _format_level(lod, indent):
    if lod['level'] == 0:
        label = 'LOD0 (main mesh)'
    else:
        label = f"LOD{lod['level']} (distance {lod['distance']:g})"
    return f"{indent}{label}: {lod['vertices']} vertices, {lod['triangles']} triangles"


def format_lod_summary(report):
    lines = []
    for mesh in report['meshes']:
        lines.append(f"mesh {mesh['meshId']}: vertex buffer holds {
                     mesh['vertexBufferVertices']} vertices")
        if len(mesh['subsets']) <= 1:
            lines.extend(_format_level(lod, '  ') for lod in mesh['lods'])
            continue
        for index, subset in enumerate(mesh['subsets'], start=1):
            lines.append(f"  subset {index}:")
            lines.extend(_format_level(lod, '    ')
                         for lod in subset['levels'])
    return '\n'.join(lines)


def validate_qt_mesh(path):
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 28:
        raise ValueError('file too small')

    # footer header
    multiHeaderStartOffset_ = len(data) - MULTI_HEADER_STRUCT_SIZE
    file_id, file_version, entries_offset, mesh_count = struct.unpack_from(
        '<4I', data, multiHeaderStartOffset_)
    print(f'mesh count: {mesh_count}')

    if file_id != MULTI_FILE_ID:
        raise ValueError(f'invalid multi-mesh file id: {file_id}')

    if file_version != FILE_VERSION:
        raise ValueError(f'invalid file_version file id: {file_version}')

    if mesh_count < 1:
        raise ValueError('no meshes recorded in footer')

    meshOffsets = {}
    meshes = []
    for idx in range(mesh_count):
        fileOffset_ = multiHeaderStartOffset_ - MULTI_ENTRY_STRUCT_SIZE * \
            mesh_count + MULTI_ENTRY_STRUCT_SIZE * idx
        offset_, id_, padding_ = struct.unpack_from('<QII', data, fileOffset_)
        meshOffsets[id_] = offset_
        print(f'meshes: {id_} {offset_}')
        meshes.append(read_mesh(data, id_, offset_))

    return {
        'multiMesh': {'fileId': file_id, 'fileVersion': file_version, 'entriesOffset': entries_offset, 'meshCount': mesh_count},
        'meshes': meshes
    }


def main():
    ap = argparse.ArgumentParser(
        description='Validate and inspect a Qt Quick 3D .mesh file')
    ap.add_argument('mesh_file')
    ap.add_argument('--json', action='store_true',
                    help='print the full parsed structure as JSON instead of the LOD summary')
    args = ap.parse_args()
    report = validate_qt_mesh(args.mesh_file)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_lod_summary(report))


if __name__ == '__main__':
    main()
