# Qt Quick 3D Balsam Exporter — Blender Plugin

A Blender add-on that exports your scene in exactly the same structure as
Qt's **balsam** asset-import tool, ready to drop into a Qt Quick 3D project.

---

## What it exports

| Asset type        | Output                                      |
|-------------------|---------------------------------------------|
| Meshes            | `meshes/<name>.mesh`  (native format v7)    |
| Textures / Images | `images/<name>.png`                         |
| Materials         | Inline `PrincipledMaterial {}` in QML       |
| Cameras           | `PerspectiveCamera` / `OrthographicCamera`  |
| Lights            | `PointLight`, `DirectionalLight`, `SpotLight` |
| Animations        | `Timeline` + `KeyframeGroup` blocks         |
| Scene hierarchy   | Nested `Node {}` / `Model {}` tree          |
| Resource file     | `<scene>.qrc`                               |
| CMake snippet     | `CMakeLists_qt3d_snippet.txt`               |
| Manifest          | `export_manifest.json`                      |

---

## Output directory structure

```
MyScene/
├── MyScene.qml            ← main QML component (Node root)
├── MyScene.qrc            ← Qt resource file
├── CMakeLists_qt3d_snippet.txt
├── export_manifest.json
├── meshes/
│   ├── Cube.mesh
│   └── Character.mesh
└── images/
    ├── albedo.png
    ├── normal.png
    └── roughness.png
```

---

## Installation

1. Open Blender → **Edit → Preferences → Add-ons → Install**
2. Select `qt_balsam_exporter.zip`
3. Enable **Import-Export: Qt Quick 3D Balsam Exporter**

---

## Usage

**File → Export → Qt Quick 3D (.qml)**

Choose your output path (e.g. `MyProject/assets/MyScene.qml`).  
All sub-directories (`meshes/`, `images/`) are created automatically beside the `.qml`.

### Export Options

| Option              | Default | Description                                      |
|---------------------|---------|--------------------------------------------------|
| Cameras             | ✗       | Export cameras as QML camera nodes               |
| Lights              | ✗       | Export lights as QML light nodes                 |
| Animations          | ✗       | Export keyframe animations via Timeline          |
| Apply Modifiers     | ✓       | Apply mesh modifiers before exporting            |
| Selected Only       | ✗       | Export only currently selected objects           |
| Convert (Z → Y)     | ✓       | Convert Z-up to Y-up coordinate system           |

---

## Using the exported files in Qt Quick 3D

### 1. Add mesh conversion to CMakeLists.txt

Qt's balsam tool converts `.glb` → Qt's native `.mesh` at build time.
Add to your `CMakeLists.txt`:

```cmake
find_package(Qt6 REQUIRED COMPONENTS Quick3D)

# Auto-convert all exported .glb files
qt6_add_balsam(
    my_target
    FILES
        assets/meshes/Cube.mesh
        assets/meshes/Character.mesh
    OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/assets/meshes
)
```

Or if you use the `.qrc` directly:

```cmake
qt_add_resources(my_target "scene_assets"
    PREFIX "/"
    FILES
        assets/MyScene.qml
        assets/meshes/Cube.mesh
        assets/images/albedo.png
)
```

### 2. Use in QML

```qml
import QtQuick
import QtQuick3D

View3D {
    anchors.fill: parent

    environment: SceneEnvironment {
        clearColor: "#222"
        backgroundMode: SceneEnvironment.Color
    }

    // Drop the exported component in directly
    MyScene {
        id: myScene
    }
}
```

### 3. Mesh sources

The exported QML references meshes as:
```qml
Model {
    source: "qrc:/meshes/Cube.mesh"
    ...
}
```

After balsam conversion these become `"qrc:/meshes/Cube.mesh"` — 
update the `source` paths in your QML (or use a build step to do it automatically).

---

## Material mapping (Blender → Qt)

| Blender Principled BSDF input | Qt PrincipledMaterial property |
|-------------------------------|-------------------------------|
| Base Color                    | `baseColor` / `baseColorMap`  |
| Metallic                      | `metalness` / `metalnessMap`  |
| Roughness                     | `roughness` / `roughnessMap`  |
| Normal                        | `normalMap`                   |
| Emission Color                | `emissiveFactor` / `emissiveMap` |
| Alpha                         | `opacity` + `alphaMode`       |
| IOR                           | `indexOfRefraction`           |

---

## Coordinate system

Blender uses Z-up, right-hand.  Qt Quick 3D uses Y-up, left-hand.

The plugin automatically converts:

| Axis  | Blender | Qt Quick 3D |
|-------|---------|-------------|
| Right | +X      | +X          |
| Up    | +Z      | +Y          |
| Back  | +Y      | −Z          |

---

## Requirements

- Blender 4.4 or newer
- Qt 6.11 or newer (for full Quick 3D API coverage)

---

## License

MIT — free to use in commercial and open-source Qt projects.


## Keep selected objects unmirrored

Add a boolean Blender custom property `neverMirror` to an object:

```python
bpy.data.objects["DC.1500Amp.001"]["neverMirror"] = True
```

On export, the object keeps the world position produced by its mirrored
ancestors. Its shape and orientation are restored using the same transform
chain with negative scale signs removed; positive scale magnitudes remain.
Children follow this restored frame. Their own local transforms remain intact.
UV coordinates and mesh files are unchanged, and material selection uses the
corrected world transform.

The flag can also be set on a collection-instance object, or on its referenced
collection to protect all instances of that collection. A plain organizational
collection is not a transform node; set the flag on its objects instead.

The exporter inserts two QML Node wrappers when compensation is needed. This
also handles rotated, nonuniformly scaled ancestors without losing shear.
Collections containing protected descendants may get a `_Restore_...` component
suffix when their compensation differs. Instances with identical compensation
reuse that component regardless of position.

This is export-time compensation, not a runtime constraint. Re-export after
changing ancestor transforms. Zero object or ancestor scales cannot be inverted
and are rejected. Existing materials/shaders do not need UV reflection enabled
for a restored object. Reload the addon after installing this change.
