# Qt Quick 3D Balsam Exporter — Blender add-on

Export Blender scenes to QML and native Qt Quick 3D `.mesh` files, and import
Qt `.mesh` geometry back into Blender. Despite the name, **exported meshes do
not need a balsam conversion step**.

This version includes Shipmate-specific material and interactive-object support.
Generated scenes import `LogicModule as LM`; they are not standalone Qt-only
assets without that module or corresponding adjustments to the generated QML.

## Requirements and installation

- Add-on version: **2.2.0**; declared minimum Blender version: **4.4**.
- The current development setup uses Blender **5.2** and Qt **6.11**. Not every
  Blender/Qt version combination has been verified.
- Qt Quick 3D is required by the generated scene. Physics and animation exports
  also use `QtQuick3D.Physics` and `QtQuick.Timeline`, respectively.
- Shipmate's `LogicModule` must be available on the QML import path. Mirror
  variants use its `PrincipledBSDFMaterial`; interactive helpers also use LM types.

Install the add-on folder as `qt_balsam_exporter` in Blender's scripts/addons
location, or install an archive containing that folder through Blender's add-on
installation UI. Enable **Qt Quick 3D Balsam Exporter Plugin** in Preferences.
Restart Blender after updating an already loaded copy.

The repository contains local material/shader links in some development checkouts.
The export routine does **not** copy those runtime assets into the output folder;
provide them through the application's `LogicModule` deployment.

## Export a scene

Choose **File → Export → Qt Quick 3D (.qml)** and select a destination such as
`assets/MyScene.qml`. Use a QML component filename beginning with an uppercase
letter. Meshes, images, collection components, and resource helpers are written
beside it.

| Option | Default | Current behavior |
| --- | --- | --- |
| Cameras | Off | Export perspective and orthographic cameras. |
| Lights | Off | Export supported point, directional, and spot lights. |
| Animations | Off | Generate Timeline blocks for object location, Euler rotation, and scale; see limitations below. |
| Apply Modifiers | On | Export evaluated mesh geometry. |
| Generate LODs | Off | Embed additional index ranges in `_LODs.mesh` files. |
| Selected Only | Off | Present in the UI, but not currently applied by scene traversal. |
| Convert Coordinates (Z-up → Y-up) | On | Convert mesh geometry and object transforms to the export coordinate convention. |

The exporter handles meshes, curves, surfaces, and text geometry, plus Empty
nodes and collection instances. It traverses parented children, including meshes
and collection instances attached to an instance object.

### Python invocation

Run this inside Blender with the add-on enabled:

```python
import bpy

bpy.ops.export_scene.qt_balsam(
    filepath="/absolute/path/to/assets/MyScene.qml",
    export_cameras=False,
    export_lights=False,
    export_animations=False,
    apply_modifiers=True,
    generate_lods=False,
    convert_coords=True,
)
```

### Output layout

```text
assets/
├── MyScene.qml
├── Collectionname.qml              # reusable collection components, when needed
├── MyScene.qrc
├── CMakeLists_qt3d_snippet.txt
├── export_manifest.json
├── meshes/
│   ├── Cube.mesh
│   └── Library.blend/
│       └── LinkedMesh.mesh
└── images/
    ├── Albedo_png.png
    └── Library_blend/
        └── LinkedTexture_png.png
```

Names are sanitized where the exporter requires identifiers or filenames. Linked
mesh and image directories follow different naming rules; use the paths actually
written into QML and the resource file rather than reconstructing them yourself.
The manifest records the scene name, main QML file, mesh paths, image mapping, and
material IDs. The `.qrc` also includes generated collection components.

Images are saved as PNG using `image.save()` for both packed and unpacked images.
Their original Blender filepath and valid file-format setting are restored after
saving. Export is not a byte-for-byte copy of the original image file.

## Collections, visibility, and reuse

- Collection instances reference generated QML components. Repeated instances
  reuse source geometry where possible.
- Separate objects with different evaluated modifier results can receive distinct
  mesh filenames even when they share a Blender mesh datablock.
- Objects with `hide_render=True` are omitted, including during recursive export.
  A hidden object also stops traversal of its children.
- A collection used as the entry point of an instance can be hidden in Blender;
  that does not suppress the entire instantiated component. Hidden child
  collections beneath it are skipped.
- Mesh objects with `visible_camera=False` are emitted with `visible: false`.

Mirroring and `neverMirror` compensation can require material/component variants.
Do not remove generated suffixes without checking whether those variants contain
meaningfully different transforms or material settings.

## Coordinates and mirrored objects

With coordinate conversion enabled, positions follow:

```text
Blender (x, y, z) → Qt (x, z, -y)
```

Blender's vertical Z becomes Qt's vertical Y. This basis conversion is a rotation,
not an additional reflection. Signed scale is mapped to the corresponding axes;
world-transform determinant checks account for mirrored ancestors and collection
instances.

Material variants can emit `shipmateMirroredInstance`, `shipmateSignedScale`,
`shipmateUvScale`, and `shipmateUvOffset`. The exporter currently leaves mirror UV
scale/offset at `(1, 1)` and `(0, 0)`: reflecting geometry does not itself change
its authored UV coordinates. It does not generate per-island UV restoration regions.

### Keep selected objects unmirrored

Add a boolean Blender custom property `neverMirror` to an object:

```python
bpy.data.objects["DC.1500Amp.001"]["neverMirror"] = True
```

The object keeps the world position produced by its mirrored ancestors. Its shape
and orientation are restored using the transform chain with negative scale signs
removed; positive scale magnitudes remain. Children follow this restored frame
with their own local transforms intact. UV coordinates and mesh files are
unchanged, and material selection uses the corrected world transform.

The flag can also be set on a collection-instance object or on its referenced
collection to protect its instances. An organizational collection is not a
transform node; set the flag on its objects instead.

When needed, the exporter inserts two `Node` wrappers to retain compensation
through rotated, nonuniformly scaled ancestors, including shear. Collections
with protected descendants may receive a `_Restore_...` component suffix.
Identical compensation reuses the same component regardless of position.

This is export-time compensation: re-export after changing ancestor transforms.
Zero object or ancestor scales cannot be inverted and are rejected. Restored
objects do not need an additional texture reflection to undo the same mirroring.

## Materials and textures

Ordinary materials use Qt `PrincipledMaterial`. Instances requiring mirror
metadata use `LM.PrincipledBSDFMaterial`. Exported comments include Blender node
information and `// users: N`, where `N` is Blender's material datablock user count.

| Blender input | Main QML mapping |
| --- | --- |
| Base Color | `baseColor`, `baseColorMap` |
| Metallic | `metalness`, `metalnessMap` |
| Roughness | `roughness`, `roughnessMap` |
| Normal | `normalMap`, `normalStrength` |
| Emission | `emissiveFactor`, `emissiveMap`; custom material also supports emission strength inputs |
| Alpha | `opacity`, `opacityMap`, `alphaMode` |
| IOR | `indexOfRefraction` |
| Coat | Clearcoat amount, roughness, and supported texture inputs |

The custom-material path additionally exports supported anisotropy, subsurface,
sheen, and other BSDF inputs. This is a mapping of supported nodes and links,
not a complete Blender shader compiler or a promise of identical rendering.

For Principled BSDF export, `alphaMode` is `Blend` when the Alpha input is below
one or has a supported image connection; otherwise it is `Opaque`. Merely having
an alpha channel in a base-color image does not automatically select blending.
Connect the intended image alpha to the BSDF Alpha input. RGB black/white alone
does not indicate transparency.

Backface culling follows `use_backface_culling`: disabled becomes `NoCulling`;
enabled becomes `BackFaceCulling`, or `FrontFaceCulling` for an odd reflection.
Supported texture-channel routes are exported as channel properties, with custom
material flags where a scalar channel drives a color input.

Image Texture node settings determine filtering: `Closest` selects nearest
filtering without mipmaps; other interpolation modes use linear filtering.
Sphere/Tube projection disables mipmaps in the current policy. Cubic/Smart are
approximated by linear filtering. Supported vector-chain scale is exported as UV
scale/offset settings; arbitrary procedural coordinate graphs are not reproduced.

Shared `MaterialsLibrary.qml` generation and global hash-based image/material
reuse belong to Shipmate's separate asset-processing scripts, not this add-on.
The initial export keeps material declarations in generated QML.

## Physics and interactive helpers

Blender passive rigid bodies become `StaticRigidBody`; active bodies become
`DynamicRigidBody`. The body wraps the visual model and its descendants. Active
body mass and kinematic state are exported. Current shape mappings include Box,
Sphere, Capsule, Convex Hull, and Mesh. Mirror variants can generate separate
transformed collision meshes.

Check collision geometry in Qt: primitive dimensions are not fully translated,
and nested/mirrored physics is not guaranteed to match Blender's simulation.
Other Blender collision-shape types are not implemented by the current mapping.

The 3D View **Add → Shipmate** menu provides **Qml.Hatch**, **Qml.Rheostat**, and
**Qml.AnimatedGauge** helpers. Their custom properties are translated into the
corresponding Shipmate QML components.

## Import a Qt mesh into Blender

Choose **File → Import → Qt Quick 3D Mesh (.mesh)**. Coordinate conversion
(Y-up → Z-up), normals, UVs, and vertex colors are enabled by default and can be
switched off independently.

```python
bpy.ops.import_scene.qt_quick3d_mesh(
    filepath="/absolute/path/to/meshes/Cube.mesh",
    convert_coords=True,
    import_normals=True,
    import_uvs=True,
    import_colors=True,
)
```

The importer reads mesh geometry and available vertex attributes/subsets. It does
not reconstruct the source QML scene or recover Blender shader graphs, textures,
modifiers, or the original collection hierarchy from a `.mesh` file.

## Use exported resources in Qt

Use the generated resource file, or adapt `CMakeLists_qt3d_snippet.txt` to your
application target and directory layout. Do not pass these native `.mesh` files
through a `.glb`/balsam conversion step.

For example, with an existing `my_target`:

```cmake
qt_add_resources(exported_scene_sources "assets/MyScene.qrc")
target_sources(my_target PRIVATE ${exported_scene_sources})
```

The generated `.qrc` has prefix `/` and lists paths relative to its location.
Keep generated QML components, meshes, and images together so references such as
`source: "meshes/Cube.mesh"` continue to resolve. With resources registered and
`LogicModule` available, an existing `View3D` can instantiate the root component:

```qml
import QtQuick
import QtQuick3D
import "qrc:/" as Exported

View3D {
    anchors.fill: parent
    PerspectiveCamera { id: viewCamera; position: Qt.vector3d(0, 2, 5) }
    camera: viewCamera
    DirectionalLight { eulerRotation.x: -45 }
    Exported.MyScene {}
}
```

Adjust the camera and scene units for your asset. Resource paths must be kept
consistent if a later build or asset-processing step changes their prefix.

## Current limitations and troubleshooting

- **Selection:** `Selected Only` is exposed but not wired into traversal. Do not
  rely on it to exclude other scene objects.
- **Animation:** the optional exporter uses the legacy action F-curve API and
  generated node-ID targets. Some object writers do not emit those IDs. Treat
  Timeline export as experimental, particularly with newer Blender action APIs.
- **LOD:** levels sample subsets of the original triangles (55%, 25%, 8%), then
  add an empty terminal range. This is not topology-preserving mesh simplification;
  inspect results for holes and disappearance before enabling it in production.
- **Shader graphs:** material selection takes the first encountered Principled
  or Transparent BSDF rather than evaluating every branch of the active output.
  Bake unsupported procedural/mixed shader effects into textures when necessary.
- **Missing LM types:** install/deploy the matching Shipmate `LogicModule`.
  Material/shader copying is disabled in the exporter.
- **Unexpected transparency or mirrored labels:** inspect Alpha connections,
  `alphaMode`, mirror metadata, and whether `neverMirror` is appropriate. Avoid
  applying both geometry restoration and an extra UV reflection unintentionally.
- **Re-exporting:** use a dedicated output directory. Generated files are written
  there; obsolete files from earlier exports are not automatically cleaned up.

## Source layout

| File | Responsibility |
| --- | --- |
| `__init__.py` | Operators, scene traversal, collection components, transforms, mirroring, QML and resource output |
| `qt_mesh_writer.py` | Mesh extraction, native binary writing, LOD ranges, collision transforms |
| `qt_mesh_importer.py` | Native mesh reader and Blender object creation |
| `qt_mesh_validate.py` | Mesh-format validation utilities |
| `qt_bsdf_mat_importer.py` | Blender material and image conversion to QML |
| `shipmate/` | Interactive Shipmate helper objects and exporters |

## License

The bundled [LICENSE](LICENSE) contains the **GNU General Public License,
version 3**. Consult that file for the license terms.
