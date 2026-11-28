import math

from mathutils import Quaternion


def initial_transform(obj, convert_coords=True):
    position = tuple(obj.location)
    if obj.rotation_mode == 'QUATERNION':
        rotation = obj.rotation_quaternion.copy()
    elif obj.rotation_mode == 'AXIS_ANGLE':
        angle, x, y, z = obj.rotation_axis_angle
        rotation = Quaternion((x, y, z), angle)
    else:
        rotation = obj.rotation_euler.to_quaternion()
    if convert_coords:
        position = (position[0], position[2], -position[1])
        rotation = Quaternion((rotation.w, rotation.x, rotation.z, -rotation.y))
    angles = tuple(math.degrees(value) for value in rotation.to_euler('ZXY'))
    return position, angles
