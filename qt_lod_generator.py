"""
Geometric LOD generation for the Qt Balsam exporter.

Every generated level is an index-only simplification of LOD0. Edge collapses keep
one of the existing vertices, so the LOD vertex buffer is LOD0's vertex buffer.
Collapses are ordered by the quadric error metric (Garland and Heckbert). Subset borders
and non-manifold edges are locked; open mesh boundaries may shrink along their line.

Distances are not stored here: the writer sets them from each level's vertex count (see
qt_mesh_writer), in mesh-local units.

With normal recalculation enabled, the normals of the generated triangles are rebuilt
like Qt's importer does it: faces within the merge angle share a smoothed normal, and
a vertex whose smoothed normal differs from its LOD0 normal by more than the split
angle is duplicated with the new normal. Duplicates are appended after LOD0 vertices.
"""
import heapq
import math
from collections import defaultdict

import numpy as np

from .qt_simplifier import recalculate_normals


def triangles_from_flat(flat):
    """Group a flat index list into (a, b, c) tuples."""
    it = iter(flat)
    return list(zip(it, it, it))


def lod_normal_angles(options):
    """
    Return (merge, split) in degrees when LOD normal recalculation is enabled, else None.
    Angles are clamped to 0..270 like Qt's importer does.
    """
    if not options or not options.get("recalculate_normals"):
        return None
    merge = min(max(float(options.get("merge_angle", 60.0)), 0.0), 270.0)
    split = min(max(float(options.get("split_angle", 25.0)), 0.0), 270.0)
    return merge, split


def _triangle_normal(points, tri):
    a, b, c = points[tri[0]], points[tri[1]], points[tri[2]]
    return np.cross(b - a, c - a)


def _plane_quadric(points, tri):
    normal = _triangle_normal(points, tri)
    length = float(np.linalg.norm(normal))
    if length <= 1e-30:
        return None
    normal = normal / length
    plane = np.array([normal[0], normal[1], normal[2], -float(np.dot(normal, points[tri[0]]))])
    return np.outer(plane, plane)


class _EdgeCollapser:
    """Quadric edge-collapse simplification of one triangle list (global vertex ids)."""

    def __init__(self, points, triangles, locked, boundary=()):
        self.points = points
        self.tris = [tuple(t) for t in triangles]
        self.alive = [True] * len(self.tris)
        self.tri_count = len(self.tris)
        self.locked = locked
        self.removed = set()
        self.vert_tris = defaultdict(set)
        self.quadrics = defaultdict(lambda: np.zeros((4, 4)))
        self.heap = []
        self.serial = 0
        for t, tri in enumerate(self.tris):
            for v in tri:
                self.vert_tris[v].add(t)
            quadric = _plane_quadric(points, tri)
            if quadric is not None:
                for v in tri:
                    self.quadrics[v] = self.quadrics[v] + quadric
        for x, y, tri in boundary:
            quadric = _boundary_quadric(points, x, y, tri)
            if quadric is not None:
                self.quadrics[x] = self.quadrics[x] + quadric
                self.quadrics[y] = self.quadrics[y] + quadric
        self.vertex_count = sum(1 for tris in self.vert_tris.values() if tris)

    def _neighbours(self, v):
        out = set()
        for t in self.vert_tris.get(v, ()):
            out.update(self.tris[t])
        out.discard(v)
        return out

    def _flip_free(self, removed, kept, shared):
        """Reject a collapse that turns a surviving triangle over."""
        for t in self.vert_tris.get(removed, ()):
            if t in shared:
                continue
            tri = self.tris[t]
            before = _triangle_normal(self.points, tri)
            after = _triangle_normal(self.points, tuple(kept if v == removed else v for v in tri))
            if float(np.dot(before, before)) > 0.0 and float(np.dot(before, after)) <= 0.0:
                return False
        return True

    def _candidate(self, a, b):
        """Return (cost, removed, kept, shared_triangles) for edge a-b, or None if not collapsible."""
        if a in self.removed or b in self.removed:
            return None
        if a in self.locked and b in self.locked:
            return None
        shared = self.vert_tris.get(a, set()) & self.vert_tris.get(b, set())
        if not shared or len(shared) > 2 or self.tri_count - len(shared) < 1:
            return None
        # Link condition: the only common neighbours are the opposite vertices of the shared triangles.
        opposite = {v for t in shared for v in self.tris[t] if v != a and v != b}
        if (self._neighbours(a) & self._neighbours(b)) != opposite:
            return None

        quadric = self.quadrics[a] + self.quadrics[b]
        best = None
        for removed, kept in ((a, b), (b, a)):
            if removed in self.locked or not self._flip_free(removed, kept, shared):
                continue
            h = np.append(self.points[kept], 1.0)
            cost = float(h @ quadric @ h)
            if best is None or cost < best[0]:
                best = (cost, removed, kept, shared)
        return best

    def _push(self, a, b):
        cand = self._candidate(a, b)
        if cand is not None:
            self.serial += 1
            heapq.heappush(self.heap, (cand[0], self.serial, a, b))

    def _push_edges_of(self, vertices):
        pairs = set()
        for v in vertices:
            for t in self.vert_tris.get(v, ()):
                tri = self.tris[t]
                for i in range(3):
                    x, y = tri[i], tri[(i + 1) % 3]
                    pairs.add((min(x, y), max(x, y)))
        for a, b in pairs:
            self._push(a, b)

    def _collapse(self, removed, kept, shared):
        removed_live = int(bool(self.vert_tris.get(removed)))
        kept_live = int(bool(self.vert_tris.get(kept)))
        for t in list(self.vert_tris.get(removed, ())):
            if t in shared:
                self.alive[t] = False
                self.tri_count -= 1
                for v in self.tris[t]:
                    self.vert_tris[v].discard(t)
            else:
                self.tris[t] = tuple(kept if v == removed else v for v in self.tris[t])
                self.vert_tris[removed].discard(t)
                self.vert_tris[kept].add(t)
        self.quadrics[kept] = self.quadrics[kept] + self.quadrics[removed]
        self.vert_tris.pop(removed, None)
        self.removed.add(removed)
        self.vertex_count += int(bool(self.vert_tris.get(kept))) - kept_live - removed_live

    def _over(self, target, vertex_limit):
        if self.tri_count > target:
            return True
        return vertex_limit is not None and self.vertex_count > vertex_limit

    def simplify(self, targets):
        """
        Collapse edges until each (triangle count, vertex limit) pair is met. Pairs must be
        in descending vertex-limit order; a None limit means no vertex limit. Returns the
        triangle list after each pair.
        """
        self._push_edges_of(list(self.vert_tris))
        results = []
        for target, vertex_limit in targets:
            while self._over(target, vertex_limit):
                if not self.heap:
                    # Edges rejected earlier (flip or link tests) may be valid again after
                    # later collapses. Re-seed once; stop if nothing is collapsible.
                    self._push_edges_of(list(self.vert_tris))
                    if not self.heap:
                        break
                cost, _, a, b = heapq.heappop(self.heap)
                cand = self._candidate(a, b)
                if cand is None:
                    continue
                current, removed, kept, shared = cand
                if current > cost + 1e-9 * (1.0 + abs(cost)):
                    # Cost went up since this entry was queued: requeue with the current cost.
                    self.serial += 1
                    heapq.heappush(self.heap, (current, self.serial, a, b))
                    continue
                self._collapse(removed, kept, shared)
                self._push_edges_of([kept])
            results.append([self.tris[t] for t, alive in enumerate(self.alive) if alive])
        return results


MAX_LIMIT_ATTEMPTS = 6

# Penalty weight that keeps an open boundary on its original line.
BOUNDARY_WEIGHT = 100.0
# Generated levels stop at the first level with at most this many vertices.
LOD_STOP_VERTICES = 20
MAX_LOD_LEVEL = 7


def lod_level_specs(vertex_count, highest):
    """
    Vertex caps for generated levels 1..highest. Each level halves the vertex count of LOD0
    (LOD1 is half, LOD2 a quarter, ...). Generation stops at the first level whose cap is at
    or below LOD_STOP_VERTICES; the last level is held below that limit.
    """
    specs = []
    if vertex_count <= LOD_STOP_VERTICES:
        return specs
    for level in range(1, min(highest, MAX_LOD_LEVEL) + 1):
        cap = vertex_count >> level
        if level == MAX_LOD_LEVEL:
            cap = min(cap, LOD_STOP_VERTICES - 1)
        specs.append({"level": level, "max_vertices": cap})
        if cap <= LOD_STOP_VERTICES:
            break
    return specs


def _distinct_count(triangles):
    return len({v for tri in triangles for v in tri})


def _vertex_budgets(total, sizes):
    """
    Divide a vertex limit over subsets. A subset gets at most its own vertex count; budget
    a smaller subset leaves unused goes to the larger ones. Budgets sum to at most total.
    """
    budgets = [0] * len(sizes)
    remaining = total
    order = sorted(range(len(sizes)), key=lambda i: sizes[i])
    for position, i in enumerate(order):
        share = remaining // (len(order) - position)
        budgets[i] = min(sizes[i], share)
        remaining -= budgets[i]
    return budgets


def _weld(points, triangles):
    """
    Map each vertex id to one id at the same position. The exporter's vertex buffer has
    separate vertices where normals or UVs differ, so faces that meet at a point are only
    connected once their positions are compared. Output triangles keep valid LOD0 ids.
    """
    first_at = {}
    rep = {}
    for tri in triangles:
        for v in tri:
            if v not in rep:
                rep[v] = first_at.setdefault(points[v].tobytes(), v)
    return rep


def _boundary_quadric(points, a, b, tri):
    """Penalty plane through open edge a-b, perpendicular to its face."""
    normal = np.cross(points[b] - points[a], _triangle_normal(points, tri))
    length = float(np.linalg.norm(normal))
    if length <= 1e-30:
        return None
    normal = normal / length
    plane = np.array([normal[0], normal[1], normal[2], -float(np.dot(normal, points[a]))])
    return BOUNDARY_WEIGHT * np.outer(plane, plane)


def _edge_key(points, x, y):
    """Edge key by position, so vertices split by UVs or normals still match."""
    px, py = points[x].tobytes(), points[y].tobytes()
    return (px, py) if px <= py else (py, px)


def _position_edge_uses(points, triangles):
    uses = defaultdict(int)
    for tri in triangles:
        for x, y in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = _edge_key(points, x, y)
            if key[0] != key[1]:
                uses[key] += 1
    return uses


def _simplify_subset(points, triangles, targets, global_uses):
    rep = _weld(points, triangles)
    welded = []
    for tri in triangles:
        t = tuple(rep[v] for v in tri)
        if len(set(t)) == 3:
            welded.append(t)

    edge_uses = defaultdict(int)
    for a, b, c in welded:
        for x, y in ((a, b), (b, c), (c, a)):
            edge_uses[(min(x, y), max(x, y))] += 1
    # An edge used once here and nowhere else is an open mesh boundary and may shrink.
    # A subset border (shared with another subset) or a non-manifold edge stays locked.
    locked = set()
    boundary = []
    for a, b, c in welded:
        for x, y in ((a, b), (b, c), (c, a)):
            uses = edge_uses[(min(x, y), max(x, y))]
            if uses == 1 and global_uses[_edge_key(points, x, y)] == 1:
                boundary.append((x, y, (a, b, c)))
            elif uses != 2:
                locked.add(x)
                locked.add(y)
    return _EdgeCollapser(points, welded, locked, boundary).simplify(targets)


def build_generated_lods(points, normals, ranges, indices, specs, vertex_base, angles=None, warnings=None):
    """
    Build generated LOD levels for every subset.

    points: (V, 3) float64 LOD0 positions.
    normals: (V, 3) float64 LOD0 normals; required when angles is set.
    ranges: (start, count) of each subset inside the flat index list.
    indices: flat LOD0 index list.
    specs: LOD_LEVELS items with 'level' and 'max_vertices', in ascending level order. The cap is on
        the distinct vertices of the level over all subsets, split normal vertices included,
        and is divided over the subsets by _vertex_budgets.
    vertex_base: index of the first vertex appended for split normals.
    angles: (merge, split) in degrees for normal recalculation, or None.
    warnings: list that receives a message for each level still above its cap.

    Returns (levels, new_vertices). levels maps level -> list with one entry per subset:
    (flat global indices, distinct position count). new_vertices lists (source vertex, unit normal) for
    the vertices appended from vertex_base onward.
    """
    subsets = [triangles_from_flat(indices[start:start + count]) for start, count in ranges]
    global_uses = _position_edge_uses(points, [tri for tris in subsets for tri in tris])
    budgets = {spec["level"]: _vertex_budgets(spec["max_vertices"], [_distinct_count(tris) for tris in subsets])
               for spec in specs if spec.get("max_vertices") is not None}

    def as_written(lod_tris):
        """Flat indices after normal recalculation, counted without appending vertices."""
        flat = [v for tri in lod_tris for v in tri]
        if angles is None or not flat:
            return flat
        return recalculate_normals(points, normals, flat, angles[0], angles[1], vertex_base, [])

    levels = {spec["level"]: [] for spec in specs}
    new_vertices = []
    for index, tris in enumerate(subsets):
        if not tris:
            for spec in specs:
                levels[spec["level"]].append(([], 0))
            continue

        caps = {spec["level"]: budgets[spec["level"]][index] if spec["level"] in budgets else None
                for spec in specs}
        limits = dict(caps)
        for _ in range(MAX_LIMIT_ATTEMPTS):
            targets = [(len(tris), limits[spec["level"]]) for spec in specs]
            results = _simplify_subset(points, tris, targets, global_uses)

            # Split normal vertices are added after simplification, so a level over its cap
            # is retried with a lower limit (without normal recalculation the result is final).
            used = {}
            overflow = False
            for j, spec in enumerate(specs):
                cap = caps[spec["level"]]
                if cap is None:
                    continue
                used[j] = len(set(as_written(results[j])))
                if used[j] > cap:
                    overflow = True
                    limits[spec["level"]] = max(0, limits[spec["level"]] - (used[j] - cap))
            if not overflow or angles is None:
                break

        if warnings is not None:
            for j, spec in enumerate(specs):
                if j in used and used[j] > caps[spec["level"]]:
                    warnings.append(f"LOD{spec['level']} subset {index + 1} has {used[j]} vertices, "
                                    f"above its share of the {spec['max_vertices']}-vertex limit")

        for j, spec in enumerate(specs):
            lod_tris = results[j]
            count = len({points[v].tobytes() for tri in lod_tris for v in tri})
            flat = [v for tri in lod_tris for v in tri]
            if angles is not None and flat:
                flat = recalculate_normals(points, normals, flat, angles[0], angles[1], vertex_base, new_vertices)
            levels[spec["level"]].append((flat, count))
    return levels, new_vertices
