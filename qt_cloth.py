"""Runtime cloth metadata; geometry and UVs remain in the ordinary Qt mesh."""
import struct
from contextlib import contextmanager
from mathutils import Vector


def cloth_modifier(obj):
    return next((m for m in getattr(obj, "modifiers", ())
                 if m.type == 'CLOTH' and m.show_render), None)


@contextmanager
def rest_cloth_mesh(obj):
    """Keep upstream modelling modifiers but do not bake a simulated cloth frame."""
    import bpy
    states = [(m, m.show_viewport) for m in obj.modifiers if m.type == 'CLOTH']
    if not states:
        yield
        return
    try:
        for modifier, _ in states:
            modifier.show_viewport = False
        bpy.context.view_layer.update()
        yield
    finally:
        for modifier, visible in states:
            modifier.show_viewport = visible
        bpy.context.view_layer.update()


def cloth_metadata(mesh):
    entries = {e['name']: e['offset'] for e in mesh['entries']}
    points, normals, pins = [], [], []
    for index in range(mesh['vertex_count']):
        offset = index * mesh['stride']
        point = Vector(struct.unpack_from('<3f', mesh['vbuf'], offset + entries[b'attr_pos']))
        points.append(point)
        normals.append(Vector(struct.unpack_from('<3f', mesh['vbuf'], offset + entries[b'attr_norm'])))
        if mesh.get('has_cloth_pins'):
            weight = struct.unpack_from('<f', mesh['vbuf'], offset + entries[b'attr_color'] + 12)[0]
            if weight > 0.5:
                pins.append(point)
    normal = sum(normals, Vector())
    if normal.length < 1e-6:
        normal = normals[0].copy()
    normal.normalize()
    up = Vector((0, 1, 0))
    up -= normal * up.dot(normal)
    if up.length < 1e-6:
        up = Vector((0, 0, 1))
        up -= normal * up.dot(normal)
    up.normalize()
    across = up.cross(normal).normalized()
    center = sum(points, Vector()) / len(points)
    if pins:
        toward = center - sum(pins, Vector()) / len(pins)
        toward -= normal * toward.dot(normal)
        if toward.length > 1e-6:
            across = toward.normalized()
            up = normal.cross(across).normalized()
    xs, ys = [v.dot(across) for v in points], [v.dot(up) for v in points]
    origin = across * min(xs) + up * ((min(ys) + max(ys)) * 0.5) + normal * center.dot(normal)
    return dict(clothOrigin=tuple(origin), clothAxisX=tuple(across),
                clothAxisY=tuple(up), clothAxisZ=tuple(normal),
                flagWidth=max(max(xs)-min(xs), 1e-6),
                flagHeight=max(max(ys)-min(ys), 1e-6),
                vertexPinWeights=bool(mesh.get('has_cloth_pins')))
