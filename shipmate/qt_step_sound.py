"""Export Blender Speaker objects as resource-backed SpatialSound QML."""
import json


def spatial_sound_lines(sound_id, depth, properties):
    """Emit one SpatialSound; callers own its pose, playback and property bindings."""
    indent = "    "
    lines = [f"{indent * depth}LM.SpatialSound {{",
             #f"{indent * (depth + 1)}id: {sound_id}"
             ]
    lines.extend(f"{indent * (depth + 1)}{name}: {value}" for name, value in properties)
    #lines.extend(f"{indent * (depth + 1)}{line}" if line else "" for line in body)
    lines.append(f"{indent * depth}}}")
    return lines


def export_speaker(obj, nid, depth, source, pos, rot, scale, distance_model, convert_coords=True, with_object_name=True):
    """Export pose separately so nested/scaled parents never transform the audio twice.

    Use Qt's native logarithmic attenuation. Blender-only audio settings remain
    metadata; distances follow the exported Node's world scale.
    """
    data = obj.data
    loops = int(data.get('loops', -1))

    controller = data.get("controller", None)
    controller = controller.strip() if isinstance(controller, str) else None
    properties = [        
        ("objectName", json.dumps(obj.name)),
        ("position", f"Qt.vector3d{pos}"), ("eulerRotation", f"Qt.vector3d{rot}"), ("scale", f"Qt.vector3d{scale}"),
        ("source", json.dumps(source)),# ("position", f"{nid}.scenePosition"),
        #("rotation", f"{nid}_aim.sceneRotation"),
        ("autoPlay", str(bool(not data.muted)).lower()),
        ("loops", 'SpatialSound.Infinite' if loops == -1 else str(loops)),
        #("property bool muted", str(bool(data.muted)).lower()),
        #("property real gain", repr(float(data.volume))),
        #("property real blenderPitch", repr(float(data.pitch))),
        #("property real minimumVolume", repr(float(data.volume_min))),
        #("property real maximumVolume", repr(float(data.volume_max))),
        #("property real referenceDistance", repr(float(data.distance_reference))),
        #("property real maximumDistance", repr(float(data.distance_max))),
        #("property real rolloff", repr(float(data.attenuation))),
        #("property real coneInnerAngle", repr(float(data.cone_angle_inner))),
        #("property real coneOuterAngle", repr(float(data.cone_angle_outer))),
        #("property real coneOuterVolume", repr(float(data.cone_volume_outer))),
        #("property string blenderDistanceModel", json.dumps(distance_model)),
        ("volume", repr(float(data.volume))),
        #("property real worldDistanceScale", f"Math.max(0.000001, Math.abs({nid}.sceneScale.x), Math.abs({nid}.sceneScale.y), Math.abs({nid}.sceneScale.z))"),
        ("size", repr(float(data.distance_reference))),
        # Blender's default maximum is float-max, unsuitable for a native cutoff.
        ("distanceCutoff", repr(float(data.distance_max))),
        ("distanceModel", "SpatialSound.Logarithmic"),
    ]
    #sound_id = nid + "_sound"
    #body = []
    if controller:
        properties.append(("controller", controller))
        #properties.append(("property bool controllerPlaying", "false"))
        #properties.append(("readonly property var soundState", "controller && controller.sound !== undefined ? controller.sound : controller"))
    #lines = ["    " * depth + "Node {", "    " * (depth + 1) + f"id: {nid}_aim"]
    #if convert_coords:
    #    lines.append("    " * (depth + 1) + "eulerRotation: Qt.vector3d(-90, 0, 0)")
    #lines.append("    " * depth + "}")
    if not with_object_name:
        properties = [(name, value) for name, value in properties if name != "objectName"]
    lines = spatial_sound_lines(nid, depth, properties)
    #lines.append("    " * depth + f"Component.onDestruction: {sound_id}.stop()")
    return lines
