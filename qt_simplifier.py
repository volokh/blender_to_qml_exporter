"""
Python port of the Qt Quick 3D LOD generator (generateMeshLevelsOfDetail in the assimp
importer) and of the meshoptimizer edge-collapse simplifier it calls.

Covered: meshopt_simplifyEdge with options 0, no attributes, no vertex locks, no prune,
no sparse remap, and meshopt_simplifyScale. All arithmetic is float32, so the results
follow the C++ code. Not covered: normal recalculation (LOD normal splitting) and the
meshopt options that are not used by Qt.

Pure numpy; no Blender modules.
"""
import math
import struct

import numpy as np

f32 = np.float32
NONE = 0xFFFFFFFF
FLT_MAX = f32(np.finfo(np.float32).max)
INF = f32(np.inf)
ZERO = f32(0.0)
ONE = f32(1.0)
TWO = f32(2.0)
QUARTER = f32(0.25)
F15 = f32(1.5)

KIND_MANIFOLD, KIND_BORDER, KIND_SEAM, KIND_COMPLEX, KIND_LOCKED = range(5)

K_CAN_COLLAPSE = (
    (1, 1, 1, 1, 1),
    (0, 1, 0, 0, 1),
    (0, 0, 1, 0, 1),
    (0, 0, 0, 1, 1),
    (0, 0, 0, 0, 0),
)
K_HAS_OPPOSITE = (
    (1, 1, 1, 1, 1),
    (1, 0, 1, 0, 0),
    (1, 1, 1, 0, 1),
    (1, 0, 0, 0, 0),
    (1, 0, 1, 0, 0),
)
NEXT_EDGE = (1, 2, 0, 1)   # next[] of fillEdgeQuadrics
NEXT_TRI = (1, 2, 0)       # next[] of pickEdgeCollapses


# ---- vector and quadric helpers (float32) ----

def _vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(v):
    length = np.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length > 0:
        return (v[0] / length, v[1] / length, v[2] / length), length
    return v, length


def _plane_quadric(a, b, c, d, w):
    aw, bw, cw, dw = a * w, b * w, c * w, d * w
    # order: a00 a11 a22 a10 a20 a21 b0 b1 b2 c w
    return [a * aw, b * bw, c * cw, a * bw, a * cw, b * cw, a * dw, b * dw, c * dw, d * dw, w]


def _quadric_from_triangle(p0, p1, p2, weight):
    p10 = _vsub(p1, p0)
    p20 = _vsub(p2, p0)
    normal, area = _normalize(_cross(p10, p20))
    distance = normal[0] * p0[0] + normal[1] * p0[1] + normal[2] * p0[2]
    return _plane_quadric(normal[0], normal[1], normal[2], -distance, np.sqrt(area) * weight)


def _quadric_from_triangle_edge(p0, p1, p2, weight):
    p10 = _vsub(p1, p0)
    lengthsq = p10[0] * p10[0] + p10[1] * p10[1] + p10[2] * p10[2]
    length = np.sqrt(lengthsq)
    p20 = _vsub(p2, p0)
    p20p = p20[0] * p10[0] + p20[1] * p10[1] + p20[2] * p10[2]
    perp, _ = _normalize((p20[0] * lengthsq - p10[0] * p20p,
                          p20[1] * lengthsq - p10[1] * p20p,
                          p20[2] * lengthsq - p10[2] * p20p))
    distance = perp[0] * p0[0] + perp[1] * p0[1] + perp[2] * p0[2]
    return _plane_quadric(perp[0], perp[1], perp[2], -distance, length * weight)


def _quadric_from_point(x, y, z, w):
    return [w, w, w, ZERO, ZERO, ZERO, -x * w, -y * w, -z * w, (x * x + y * y + z * z) * w, w]


def _qadd(Q, R):
    return [q + r for q, r in zip(Q, R)]


def _quadric_eval(Q, v):
    a00, a11, a22, a10, a20, a21, b0, b1, b2, c, _w = Q
    rx = b0 + a10 * v[1]
    ry = b1 + a21 * v[2]
    rz = b2 + a20 * v[0]
    rx = rx * TWO
    ry = ry * TWO
    rz = rz * TWO
    rx = rx + a00 * v[0]
    ry = ry + a11 * v[1]
    rz = rz + a22 * v[2]
    r = c
    r = r + rx * v[0]
    r = r + ry * v[1]
    r = r + rz * v[2]
    return r


def _quadric_error(Q, v):
    r = _quadric_eval(Q, v)
    w = Q[10]
    s = ZERO if w == 0 else ONE / w
    return np.abs(r) * s


# ---- flip tests ----

def _has_triangle_flip(a, b, c, d):
    eb = _vsub(b, a)
    ec = _vsub(c, a)
    ed = _vsub(d, a)
    nbc = _cross(eb, ec)
    nbd = _cross(eb, ed)
    ndp = nbc[0] * nbd[0] + nbc[1] * nbd[1] + nbc[2] * nbd[2]
    abc = nbc[0] * nbc[0] + nbc[1] * nbc[1] + nbc[2] * nbc[2]
    abd = nbd[0] * nbd[0] + nbd[1] * nbd[1] + nbd[2] * nbd[2]
    return ndp <= QUARTER * np.sqrt(abc * abd)


def _has_triangle_flips(adj, vpos, collapse_remap, i0, i1):
    v0 = vpos[i0]
    v1 = vpos[i1]
    for nxt, prv in adj[i0]:
        a = collapse_remap[nxt]
        b = collapse_remap[prv]
        if a == i1 or b == i1 or a == b:
            continue
        if _has_triangle_flip(vpos[a], vpos[b], v0, v1):
            return True
    return False


def _complex_target(v, target, remap, loop, loopback):
    r = remap[target]
    if loop[v] != NONE and remap[loop[v]] == r:
        return loop[v]
    if loopback[v] != NONE and remap[loopback[v]] == r:
        return loopback[v]
    return target


# ---- topology ----

def _edge_adjacency(indices, vertex_count, remap):
    """Per vertex, the (next, prev) pairs of the faces around it, in face order."""
    adj = [[] for _ in range(vertex_count)]
    for t in range(0, len(indices), 3):
        a, b, c = indices[t], indices[t + 1], indices[t + 2]
        if remap is not None:
            a, b, c = remap[a], remap[b], remap[c]
        adj[a].append((b, c))
        adj[b].append((c, a))
        adj[c].append((a, b))
    return adj


def _has_edge(adj, a, b):
    return any(nxt == b for nxt, _ in adj[a])


def _position_remap(positions):
    """remap: each vertex -> first vertex with an identical position; wedge: cyclic list of them."""
    count = len(positions)
    first = {}
    remap = [0] * count
    for i, p in enumerate(positions.tolist()):
        key = (p[0] + 0.0, p[1] + 0.0, p[2] + 0.0)
        remap[i] = first.setdefault(key, i)
    wedge = list(range(count))
    for i in range(count):
        if remap[i] != i:
            r = remap[i]
            wedge[i] = wedge[r]
            wedge[r] = i
    return remap, wedge


def _classify(adj, remap, wedge, count):
    """Vertex kinds plus loop/loopback (the open half-edges), as classifyVertices does."""
    loop = [NONE] * count
    loopback = [NONE] * count
    openinc = loopback   # the C++ code aliases these arrays; keep that
    openout = loop
    for vertex in range(count):
        for target, _ in adj[vertex]:
            if target == vertex:
                openinc[vertex] = vertex
                openout[vertex] = vertex
            elif not _has_edge(adj, target, vertex):
                openinc[target] = vertex if openinc[target] == NONE else target
                openout[vertex] = target if openout[vertex] == NONE else vertex

    kind = [KIND_LOCKED] * count
    for i in range(count):
        if remap[i] == i:
            if wedge[i] == i:
                openi, openo = openinc[i], openout[i]
                if openi == NONE and openo == NONE:
                    kind[i] = KIND_MANIFOLD
                elif openi != NONE and openo != NONE and remap[openi] == remap[openo] and openi != i:
                    kind[i] = KIND_SEAM
                elif openi != i and openo != i:
                    kind[i] = KIND_BORDER
                else:
                    kind[i] = KIND_LOCKED
            elif wedge[wedge[i]] == i:
                w = wedge[i]
                openiv, openov = openinc[i], openout[i]
                openiw, openow = openinc[w], openout[w]
                if (openiv != NONE and openiv != i and openov != NONE and openov != i and
                        openiw != NONE and openiw != w and openow != NONE and openow != w):
                    if remap[openiv] == remap[openow] and remap[openov] == remap[openiw] and remap[openiv] != remap[openov]:
                        kind[i] = KIND_SEAM
                    else:
                        kind[i] = KIND_LOCKED
                else:
                    kind[i] = KIND_LOCKED
            else:
                kind[i] = KIND_LOCKED
        else:
            kind[i] = kind[remap[i]]
    return kind, loop, loopback


def _rescale(positions):
    """Positions normalised to [0, 1] by the largest axis extent; returns (points, extent)."""
    p = np.asarray(positions, dtype=np.float32)
    mn = p.min(axis=0)
    mx = p.max(axis=0)
    extent = ZERO
    for k in range(3):
        d = mx[k] - mn[k]
        if not (d < extent):
            extent = d
    scale = ZERO if extent == 0 else ONE / extent
    out = []
    for x, y, z in p.tolist():
        out.append(
            ((f32(x) - mn[0]) * scale, (f32(y) - mn[1]) * scale, (f32(z) - mn[2]) * scale))
    return out, extent


# ---- simplifier steps ----

def _pick_collapses(indices, remap, kind, loop, loopback):
    out = []
    for t in range(0, len(indices), 3):
        for e in range(3):
            i0 = indices[t + e]
            i1 = indices[t + NEXT_TRI[e]]
            if remap[i0] == remap[i1]:
                continue
            k0, k1 = kind[i0], kind[i1]
            if not (K_CAN_COLLAPSE[k0][k1] | K_CAN_COLLAPSE[k1][k0]):
                continue
            if K_HAS_OPPOSITE[k0][k1] and remap[i1] > remap[i0]:
                continue
            if k0 in (KIND_BORDER, KIND_SEAM) and k1 != KIND_MANIFOLD and loop[i0] != i1:
                continue
            if k1 in (KIND_BORDER, KIND_SEAM) and k0 != KIND_MANIFOLD and loopback[i1] != i0:
                continue
            if K_CAN_COLLAPSE[k0][k1] & K_CAN_COLLAPSE[k1][k0]:
                out.append([i0, i1, True, None])
            elif K_CAN_COLLAPSE[k0][k1]:
                out.append([i0, i1, False, None])
            else:
                out.append([i1, i0, False, None])
    return out


def _rank_collapses(collapses, vpos, vq, remap):
    for c in collapses:
        i0, i1, bidi = c[0], c[1], c[2]
        ei = _quadric_error(vq[remap[i0]], vpos[i1])
        ej = _quadric_error(vq[remap[i1]], vpos[i0]) if bidi else FLT_MAX
        rev = bidi and bool(ej < ei)
        c[0], c[1] = (i1, i0) if rev else (i0, i1)
        c[3] = ej if ej < ei else ei


def _sort_order(collapses):
    """Order by the top 12 bits of the float bit pattern (counting sort, stable)."""
    keys = []
    for c in collapses:
        bits = struct.unpack('<I', struct.pack('<f', float(c[3])))[0]
        key = ((bits << 1) & 0xFFFFFFFF) >> 20
        keys.append(min(key, 2048 + 512 - 1))
    return sorted(range(len(collapses)), key=keys.__getitem__)


def _perform_collapses(collapse_remap, locked, collapses, order, remap, wedge, kind, loop, loopback,
                       vpos, adj, goal, error_limit, result_error):
    edge_collapses = 0
    triangle_collapses = 0
    edge_goal = goal // 2
    count = len(order)
    for pos in range(count):
        c = collapses[order[pos]]
        if c[3] > error_limit:
            break
        if triangle_collapses >= goal:
            break
        error_goal = F15 * collapses[order[edge_goal]
                                     ][3] if edge_goal < count else FLT_MAX
        if c[3] > error_goal and c[3] > result_error and triangle_collapses > goal // 6:
            break

        i0, i1 = c[0], c[1]
        r0, r1 = remap[i0], remap[i1]
        k = kind[i0]
        if locked[r0] or locked[r1]:
            continue
        if _has_triangle_flips(adj, vpos, collapse_remap, r0, r1):
            edge_goal += 1
            continue

        if k == KIND_COMPLEX:
            v = i0
            while True:
                collapse_remap[v] = _complex_target(
                    v, i1, remap, loop, loopback)
                v = wedge[v]
                if v == i0:
                    break
        elif k == KIND_SEAM:
            s0 = wedge[i0]
            s1 = loopback[s0] if loop[i0] == i1 else loop[s0]
            if s1 == NONE:
                s1 = wedge[i1]
            collapse_remap[i0] = i1
            collapse_remap[s0] = s1
        else:
            collapse_remap[i0] = i1

        locked[r0] = True
        locked[r1] = True
        triangle_collapses += 1 if k == KIND_BORDER else 2
        edge_collapses += 1
        if result_error < c[3]:
            result_error = c[3]
    return edge_collapses, result_error


def _update_quadrics(collapse_remap, vq, remap):
    for i in range(len(collapse_remap)):
        if collapse_remap[i] == i:
            continue
        i1 = collapse_remap[i]
        r0, r1 = remap[i], remap[i1]
        if i == r0:
            vq[r1] = _qadd(vq[r1], vq[r0])


def _remap_loops(loop, collapse_remap):
    for i in range(len(loop)):
        if loop[i] != NONE:
            l = loop[i]
            r = collapse_remap[l]
            if i == r:
                loop[i] = collapse_remap[loop[l]] if loop[l] != NONE else NONE
            else:
                loop[i] = r


def _remap_index_buffer(indices, collapse_remap, remap):
    out = []
    for t in range(0, len(indices), 3):
        v0 = collapse_remap[indices[t]]
        v1 = collapse_remap[indices[t + 1]]
        v2 = collapse_remap[indices[t + 2]]
        r0, r1, r2 = remap[v0], remap[v1], remap[v2]
        if r0 != r1 and r0 != r2 and r1 != r2:
            out.extend((v0, v1, v2))
    return out


def simplify_edge(indices, positions, target_index_count):
    """
    meshopt_simplifyEdge(options=0, target_error=FLT_MAX) on a position-only mesh.
    indices: flat vertex ids; positions: (V, 3) float32 array.
    Returns (new flat indices, error) where error is the float32 value written to resultError.
    """
    vertex_count = len(positions)
    result = [int(i) for i in indices]

    adj0 = _edge_adjacency(result, vertex_count, None)
    remap, wedge = _position_remap(np.asarray(positions, dtype=np.float32))
    kind, loop, loopback = _classify(adj0, remap, wedge, vertex_count)
    vpos, _ = _rescale(positions)

    vq = [[ZERO] * 11 for _ in range(vertex_count)]
    for t in range(0, len(result), 3):
        i0, i1, i2 = result[t], result[t + 1], result[t + 2]
        Q = _quadric_from_triangle(vpos[i0], vpos[i1], vpos[i2], ONE)
        vq[remap[i0]] = _qadd(vq[remap[i0]], Q)
        vq[remap[i1]] = _qadd(vq[remap[i1]], Q)
        vq[remap[i2]] = _qadd(vq[remap[i2]], Q)

    factor = f32(1e-7)
    for i in range(vertex_count):
        if remap[i] != i:
            continue
        w = vq[i][10] * factor
        x, y, z = vpos[i]
        vq[i] = _qadd(vq[i], _quadric_from_point(x, y, z, w))

    for t in range(0, len(result), 3):
        for e in range(3):
            i0 = result[t + e]
            i1 = result[t + NEXT_EDGE[e]]
            k0, k1 = kind[i0], kind[i1]
            if k0 != KIND_BORDER and k0 != KIND_SEAM and k1 != KIND_BORDER and k1 != KIND_SEAM:
                continue
            if (k0 == KIND_BORDER or k0 == KIND_SEAM) and loop[i0] != i1:
                continue
            if (k1 == KIND_BORDER or k1 == KIND_SEAM) and loopback[i1] != i0:
                continue
            i2 = result[t + NEXT_EDGE[e + 1]]
            edge_weight = f32(10.0) if (
                k0 == KIND_BORDER or k1 == KIND_BORDER) else f32(0.5)
            Q = _quadric_from_triangle_edge(
                vpos[i0], vpos[i1], vpos[i2], edge_weight)
            QT = _quadric_from_triangle(
                vpos[i0], vpos[i1], vpos[i2], edge_weight)
            QT[10] = ZERO
            Q = _qadd(Q, QT)
            vq[remap[i0]] = _qadd(vq[remap[i0]], Q)
            vq[remap[i1]] = _qadd(vq[remap[i1]], Q)

    result_error = ZERO
    error_limit = INF   # FLT_MAX squared overflows to infinity
    while len(result) > target_index_count:
        adj = _edge_adjacency(result, vertex_count, remap)
        collapses = _pick_collapses(result, remap, kind, loop, loopback)
        if not collapses:
            break
        _rank_collapses(collapses, vpos, vq, remap)
        order = _sort_order(collapses)
        goal = (len(result) - target_index_count) // 3
        collapse_remap = list(range(vertex_count))
        locked = [False] * vertex_count
        edge_count, result_error = _perform_collapses(
            collapse_remap, locked, collapses, order, remap, wedge, kind, loop, loopback,
            vpos, adj, goal, error_limit, result_error)
        if edge_count == 0:
            break
        _update_quadrics(collapse_remap, vq, remap)
        _remap_loops(loop, collapse_remap)
        _remap_loops(loopback, collapse_remap)
        result = _remap_index_buffer(result, collapse_remap, remap)

    return result, f32(np.sqrt(result_error))


# ---- Qt wrapper: weld, target loop, distance = error * scaleFactor ----

def _weld(all_positions, indices, normals):
    """generateVertexRemap over the referenced vertices: ids in order of first appearance."""
    pos = np.asarray(all_positions, dtype=np.float32)
    nrm = np.asarray(
        normals, dtype=np.float32) if normals is not None else None
    welded_of = {}
    first = {}
    welded_positions = []
    members = {}
    for raw in indices:
        key = pos[raw].tobytes()
        if nrm is not None:
            key += nrm[raw].tobytes()
        wid = first.get(key)
        if wid is None:
            wid = len(welded_positions)
            first[key] = wid
            welded_positions.append(pos[raw])
            members[wid] = raw
        welded_of[raw] = wid
    for raw in welded_of:
        wid = welded_of[raw]
        if raw < members[wid]:
            members[wid] = raw
    welded_indices = [welded_of[i] for i in indices]
    welded_original = [members[w] for w in range(len(welded_positions))]
    return welded_indices, np.array(welded_positions, dtype=np.float32), welded_original


def _cos_deg(angle):
    return f32(np.cos(f32(angle) * f32(math.pi / 180.0)))


def _vec(array, index):
    return (f32(array[index, 0]), f32(array[index, 1]), f32(array[index, 2]))


def _pos_key(p):
    return (float(p[0]) + 0.0, float(p[1]) + 0.0, float(p[2]) + 0.0)


def _vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _preserve_winding(positions, normals, flat_indices):
    """Keep each reduced triangle aligned with its source vertex-normal direction."""
    if normals is None:
        return flat_indices

    points = np.asarray(positions, dtype=np.float32)
    vertex_normals = np.asarray(normals, dtype=np.float32)
    triangles = np.asarray(flat_indices, dtype=np.int64).reshape(-1, 3)
    if not len(triangles):
        return flat_indices

    a, b, c = triangles.T
    face_normals = np.cross(points[b] - points[a], points[c] - points[a])
    source_normals = vertex_normals[a] + vertex_normals[b] + vertex_normals[c]
    flipped = np.einsum("ij,ij->i", face_normals, source_normals) < 0.0
    triangles[flipped, 1], triangles[flipped, 2] = triangles[flipped,
                                                             2].copy(), triangles[flipped, 1].copy()
    return triangles.reshape(-1).tolist()


def recalculate_normals(positions, normals, flat_indices, merge_angle, split_angle, vertex_base, new_vertices):
    """
    Qt's LOD normal correction (generateMeshLevelsOfDetail). Degenerate faces are dropped; a
    corner whose smoothed normal differs from its vertex normal by more than split_angle gets a
    new vertex, id = vertex_base + len(new_vertices), appended as (source, unit normal).
    Returns the new flat index list.
    """
    pos = np.asarray(positions, dtype=np.float32)
    nrm = np.asarray(normals, dtype=np.float32)
    cos_merge = _cos_deg(merge_angle)
    cos_split = _cos_deg(split_angle)

    kept = []
    face_normals = []
    for t in range(0, len(flat_indices), 3):
        a, b, c = flat_indices[t], flat_indices[t + 1], flat_indices[t + 2]
        p0, p1, p2 = _vec(pos, a), _vec(pos, b), _vec(pos, c)
        normal, area = _normalize(_cross(_vsub(p1, p0), _vsub(p2, p0)))
        if area != 0:
            kept.extend((a, b, c))
            face_normals.extend((normal, normal, normal))

    groups = {}
    for pi, vid in enumerate(kept):
        groups.setdefault(_pos_key(_vec(pos, vid)), []).append(pi)

    out = list(kept)
    for pi, vid in enumerate(kept):
        fn = face_normals[pi]
        smooth = (ZERO, ZERO, ZERO)
        for pi2 in groups[_pos_key(_vec(pos, vid))]:
            if pi2 == pi:
                smooth = _vadd(smooth, fn)
            elif _dot(face_normals[pi2], fn) >= cos_merge:
                smooth = _vadd(smooth, face_normals[pi2])
        smooth, _ = _normalize(smooth)
        if _dot(_vec(nrm, vid), smooth) < cos_split:
            out[pi] = vertex_base + len(new_vertices)
            new_vertices.append((vid, tuple(float(x)
                                for x in _normalize(smooth)[0])))
    return out


def levels_of_detail(all_positions, indices, normals=None, merge_angle=None, split_angle=None,
                     new_vertices=None, vertex_base=None):
    """
    generateMeshLevelsOfDetail. Returns [(distance, flat original indices)] with
    distance = error * scaleFactor. With merge_angle and split_angle set (not both 0) and
    normals given, the level normals are recalculated; split vertices go to new_vertices.
    """
    if new_vertices is None:
        new_vertices = []
    recalc = normals is not None and merge_angle is not None and not (
        merge_angle == 0 and split_angle == 0)
    if vertex_base is None:
        vertex_base = len(all_positions)
    welded_indices, welded_positions, welded_original = _weld(
        all_positions, indices, None)
    _, scale = _rescale(welded_positions)
    index_count = len(indices)
    index_target = 12
    last_count = 0
    lods = []
    while index_target < index_count:
        new_indices, error = simplify_edge(
            welded_indices, welded_positions, index_target)
        count = len(new_indices)
        if float(count) < float(last_count) * 1.5:
            index_target = int(float(index_target) * 1.5)
            continue
        if count == 0 or float(count) >= float(index_count) * 0.75:
            break
        original = [welded_original[v] for v in new_indices]
        original = _preserve_winding(all_positions, normals, original)
        if recalc:
            original = recalculate_normals(all_positions, normals, original, merge_angle, split_angle,
                                           vertex_base, new_vertices)
        lods.append((f32(error * scale), original))
        index_target = max(count, index_target) * 2
        last_count = count
        if error == 0:
            break
    return lods


MAX_LOD_LEVEL = 7


def triangles_from_flat(flat):
    it = iter(flat)
    return list(zip(it, it, it))


def lod_normal_angles(options):
    """(merge, split) in degrees when LOD normal recalculation is enabled, else None."""
    if not options or not options.get("recalculate_normals"):
        return None
    merge = min(max(float(options.get("merge_angle", 60.0)), 0.0), 270.0)
    split = min(max(float(options.get("split_angle", 25.0)), 0.0), 270.0)
    return merge, split


LOD_CAP_STOP = 20
LOD_CAP_LAST = 19


def _capped_levels(all_positions, indices, normals, merge, split, new_vertices, vertex_base, highest,
                   warnings=None):
    """
    Levels in LOD order (LOD1 first) with vertex caps: LOD0's distinct positions halved per level,
    the last level held below LOD_CAP_LAST. For each level the largest index target whose vertex
    count (split vertices included) fits the cap is searched; its distance is error * scaleFactor
    of that run. Stops after the first cap at or below LOD_CAP_STOP.
    """
    recalc = normals is not None and merge is not None and not (
        merge == 0 and split == 0)
    welded_indices, welded_positions, welded_original = _weld(
        all_positions, indices, None)
    _, scale = _rescale(welded_positions)
    base = len({p.tobytes() for p in welded_positions})
    triangles = len(welded_indices) // 3

    def fit(count_triangles):
        new, error = simplify_edge(
            welded_indices, welded_positions, 3 * count_triangles)
        original = [welded_original[v] for v in new]
        original = _preserve_winding(all_positions, normals, original)
        if recalc:
            counted = recalculate_normals(
                all_positions, normals, original, merge, split, vertex_base, [])
        else:
            counted = original
        return original, error, len(set(counted))

    lods = []
    for level in range(1, highest + 1):
        cap = base >> level
        if level == MAX_LOD_LEVEL:
            cap = min(cap, LOD_CAP_LAST)
        if cap < 1:
            break
        best = None
        low, high = 1, triangles
        while low <= high:
            mid = (low + high) // 2
            result = fit(mid)
            if result[2] <= cap:
                best = result
                low = mid + 1
            else:
                high = mid - 1
        if best is None:
            if warnings is not None:
                warnings.append(f"LOD{level} cannot reach {
                                cap} vertices; generated levels stop here")
            break
        original, error, _ = best
        original = _preserve_winding(all_positions, normals, original)
        if recalc:
            original = recalculate_normals(
                all_positions, normals, original, merge, split, vertex_base, new_vertices)
        lods.append((float(f32(error * scale)), original))
        if cap <= LOD_CAP_STOP:
            break
    return lods


def build_generated_lods(points, normals, ranges, indices, highest, vertex_base, angles=None, capped=False,
                         warnings=None):
    """
    Generated LOD levels 1..highest for every subset, made like Qt's importer.
    Returns (levels, new_vertices): levels maps level -> one (flat global indices, distance)
    per subset, None where the subset has no such level. new_vertices lists the split normal
    vertices as (source vertex, unit normal), with ids from vertex_base onward.
    """
    merge, split = angles if angles is not None else (None, None)
    new_vertices = []
    per_subset = []
    for start, count in ranges:
        subset = list(indices[start:start + count])
        if not subset or len({points[v].tobytes() for v in subset}) <= LOD_CAP_STOP:
            lods = []
        elif capped:
            lods = _capped_levels(points, subset, normals, merge, split, new_vertices, vertex_base, highest,
                                  warnings=warnings)
        else:
            # Qt pushes these to the front of the LOD list, so the last level created is LOD1.
            lods = levels_of_detail(
                points, subset, normals, merge, split, new_vertices, vertex_base)[::-1]
        kept = []
        for distance, flat in lods[:highest]:
            kept.append((distance, flat))
            if len(set(flat)) <= LOD_CAP_STOP:
                break
        per_subset.append(kept)

    levels = {}
    for level in range(1, max((len(lods) for lods in per_subset), default=0) + 1):
        levels[level] = [(lods[level - 1][1], float(lods[level - 1][0])) if level <= len(lods) else None
                         for lods in per_subset]
    return levels, new_vertices


def build_meshoptimizer_lods(points, normals, ranges, indices, highest, vertex_base, angles=None,
                             capped=False, warnings=None):
    """Generate LODs with the optional meshoptimizer Python bindings."""
    try:
        import meshoptimizer
        simplify = meshoptimizer.simplify
        simplify_sloppy = getattr(meshoptimizer, "simplify_sloppy", None)
    except ImportError as exc:
        raise RuntimeError(
            "Use meshoptimizer is enabled, but the meshoptimizer package is not installed in Blender's Python."
        ) from exc

    positions = np.asarray(points, dtype=np.float32)
    merge, split = angles if angles is not None else (None, None)
    new_vertices = []
    per_subset = []

    for start, count in ranges:
        source_indices = np.asarray(
            indices[start:start + count], dtype=np.uint32)
        if count < 3 or len(np.unique(source_indices)) <= LOD_CAP_STOP:
            per_subset.append([])
            continue

        lods = []
        previous_index_count = len(source_indices)
        for level in range(1, min(int(highest), MAX_LOD_LEVEL) + 1):
            # Halving the target triangle ratio at each level keeps the exported LOD chain monotonic.
            target_index_count = max(
                3, int(len(source_indices) * (0.5 ** level)))
            target_index_count -= target_index_count % 3
            destination = np.empty(len(source_indices), dtype=np.uint32)
            simplified_count = simplify(
                destination,
                source_indices,
                positions,
                target_index_count=target_index_count,
            )
            flat = destination[:int(simplified_count)].tolist()
            # meshopt_simplify can stop above its requested target when its error bound
            # prevents further collapses. For distant LODs, try its faster, less
            # conservative simplifier before giving up on this subset.
            target_is_missed = len(flat) > max(
                3, int(target_index_count * 1.25))
            if len(flat) >= previous_index_count or target_is_missed:
                if simplify_sloppy is None:
                    if len(flat) >= previous_index_count:
                        break
                else:
                    simplified_count = simplify_sloppy(
                        destination,
                        source_indices,
                        positions,
                        target_index_count=target_index_count,
                        target_error=1.0,
                    )
                    sloppy_flat = destination[:int(simplified_count)].tolist()
                    if len(sloppy_flat) >= 3 and len(sloppy_flat) < previous_index_count \
                            and len(sloppy_flat) < len(flat):
                        flat = sloppy_flat
            if len(flat) < 3 or len(flat) >= previous_index_count:
                break
            flat = _preserve_winding(positions, normals, flat)
            if angles is not None:
                flat = recalculate_normals(
                    positions, normals, flat, merge, split, vertex_base, new_vertices)
            lods.append((flat, 0.0))
            previous_index_count = len(flat)
            if len(set(flat)) <= LOD_CAP_STOP:
                break
        per_subset.append(lods)

    levels = {}
    for level in range(1, max((len(lods) for lods in per_subset), default=0) + 1):
        levels[level] = [lods[level - 1] if level <=
                         len(lods) else None for lods in per_subset]
    return levels, new_vertices
