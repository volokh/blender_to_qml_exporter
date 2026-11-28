<a href="https://buymeacoffee.com/konvol" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174">
</a>
<a href="https://www.paypal.com/donate/?hosted_button_id=5HG4V7UA7EP6U" target="_blank">
  <img src="https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif" alt="PayPal">
</a>

# Qt Quick 3D Balsam Exporter — Blender add-on

Export Blender scenes to QML and native Qt Quick 3D `.mesh` files, and import
Qt `.mesh` geometry back into Blender. Despite the name, **exported meshes do
not need a balsam conversion step**.

This version includes Shipmate-specific material and interactive-object support.
Generated files import `LogicModule as LM` only when they use `LM.` types (for
example Shipmate objects, flags, or LM materials). Those files are not standalone
Qt-only assets without that module or corresponding adjustments to the generated QML.

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

Collection component names preserve internal capitalization: `TraficLights`
exports as `TraficLights.qml` and is referenced as `TraficLights {}`. Local
collections and collection instances use the same component-name mapping.

| Option | Default | Current behavior |
| --- | --- | --- |
| Cameras | Off | Export perspective and orthographic cameras. |
| Lights | Off | Export supported point, directional, and spot lights. |
| Animations | Off | Generate Timeline blocks for object location, Euler rotation, and scale; see limitations below. |
| Apply Modifiers | On | Export evaluated mesh geometry. |
| Tangents and Binormals | Off | Export `attr_textan` and `attr_binormal` vertex attributes; enable when materials require a tangent basis, such as normal maps. |
| Generate LODs | Off | Automatically generate additional index ranges in `_LODs.mesh` files. With **Manual LODs** on, generated levels fill levels without assigned manual objects. |
| Use meshoptimizer | Off | Under **Generate LODs**, use the optional `meshoptimizer` Python bindings with a halving triangle-count target per LOD. Install them into Blender's Python environment to use this backend. LOD distances use the camera ranges. |
| Manual LODs | On | Use enabled per-object settings from the Qt Quick 3D LOD panel; see [Manual LODs](#manual-lods). |
| Camera Distance LODs | On | Estimate LOD transition distances using fixed camera ranges and reference camera settings; see [LOD camera ranges](#lod-camera-ranges). Disable to use the previous geometry-based values. |
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
    manual_lods=True,
    convert_coords=True,
)
```

### Output layout

```text
assets/
├── MyScene.qml
├── CollectionName.qml              # reusable collection components, when needed
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

## Object custom properties

Additional custom properties on Blender objects are exported on their corresponding
QML objects, including Shipmate controls, meshes, Empty nodes, cameras, lights,
and speakers:

| Blender custom property | Generated QML |
| --- | --- |
| `self.id = myControl` (string) | `id: myControl` |
| `self.value = root.inputValue` (string) | `value: root.inputValue` |
| `quantity = 3` (integer) | `property int quantity: 3` |
| `pressure = 1.5` (float) | `property real pressure: 1.5` |
| `closed = true` (boolean) | `property bool closed: true` |
| `input = root.inputValue` (string) | `property var input: root.inputValue` |

The `self.` prefix assigns an existing QML member instead of declaring a property.
An existing generated binding or declaration with the same name is updated, not
duplicated; nested child objects are not affected. An unprefixed property also
replaces an existing generated value if its name already exists. If both spellings
are present, the explicit `self.` value wins.

Existing custom properties owned by a Shipmate control (such as `qml_type`,
`value`, `change_step`, or animation `easing.type`) keep their original exporter
logic and are not exported a second time. Use `self.value`, for example, to
explicitly override the final QML value without changing the control's Blender
settings.

Strings are raw QML expressions: include quotes yourself for string literals.
Blank expressions, invalid property names, non-finite numeric values, and invalid
`self.id` values are export errors. QML ids must be unquoted identifiers beginning
with a lowercase letter or underscore. Arrays and groups use `var`; integers
outside the 32-bit QML `int` range use `var` with a warning.

Collection-instance properties retain the parent-scope behavior below: their
component interfaces are declared without assignments. A `self.*` property on
an instance applies only to that instance, not to the collection's members.
Member-authored custom properties keep their own values; temporary instance
overrides are not baked into additional member-property declarations.
This also applies to Shipmate control settings: a member's authored
`validator = root.validator` stays `validator: root.validator` in the shared
component, while the instance's `validator` value is assigned only in its
parent QML. No forwarding bindings are added automatically.

## Collections, visibility, and reuse

- Collection instances reference generated QML components. Repeated instances
  reuse source geometry where possible.
- Custom properties on a collection-instance EMPTY override matching custom
  properties on every object in the instantiated collection during export,
  including parented objects, child collections, and nested collection instances.
  Blender-registered runtime properties such as `cycles`, the `_RNA_UI`
  metadata entry, and `booleans` property groups are not exported as overrides.
  Other user-defined property groups remain supported.
  For example, set `closed = true` on the instance in `user.blend`; exporters
  reading `Door['closed']` or `DoorHandle.get('closed')` see `True`, even if those
  objects define `closed = false` in `library.blend`. Unrelated object properties
  remain intact. Overrides replace whole property values, not individual group
  fields; outer-instance overrides also propagate through nested instances.
  Existing property groups are recreated when applying and restoring overrides,
  avoiding Blender's restrictions on assigning dictionaries into some groups.
  The collection component declares corresponding QML properties, and each
  instance receives its own value in the parent QML, e.g.
  `GaugeAir { closed: true }`. Values are not baked into mesh filenames.
  Original Blender values are restored even if export fails; the linked library
  file is not changed. The collection keeps its normal stable component name;
  no per-instance `_Props_...` QML files are generated. Its generated QML
  component declares the union of custom-property interfaces needed by its
  instances, while each instance carries its own values in the parent QML.
  Blender floats use QML `real` (the QML equivalent of `qreal`), 32-bit integers
  use `int`, and booleans use `bool`. Strings, arrays and groups use `var`;
  integers outside the QML `int` range use `var` with a warning.
  When instance values for the same property mix integers and floats, its
  shared type is `real`; incompatible types use `var` and emit a warning.
- String custom-property values on collection instances are emitted verbatim as
  QML expressions. For `prop_1: root.prop_value`, enter `root.prop_value` in
  Blender; for a string literal, include the quotes yourself, e.g. `"value"` or
  `'value'`. Ensure identifiers are in scope in the parent QML. Blank values are
  errors. Strings inside structured property groups remain JSON string values.
- To override only one named object, add `DoorHandle.enabled = true` on the
  collection-instance EMPTY. The first dot separates the exact, case-sensitive
  Blender object name from its custom-property name. Only `DoorHandle['enabled']`
  is overridden; other objects retain their own or collection-wide value.
  Targeted overrides take precedence over collection-wide overrides and work
  inside child collections and nested collection instances. An override targeting
  an instance EMPTY itself does not become a collection-wide override for its
  members. Additional dots belong to the property name, for example
  `DoorHandle.easing.type` sets `DoorHandle['easing.type']`.
  Unmatched object names produce an export warning; empty names/properties are
  errors. The component exposes a safe property name such as
  `override_DoorHandle_enabled`. Targeted overrides win over a collection-wide
  override of the same property for that member while exporters run. Generated
  QML does not automatically bind or forward these properties to members;
  nested collection instances retain their own explicitly authored properties.
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

`Qml.Hatch` exports the EMPTY's local position and rotation as `initialPosition`
and `initialRotation` when nonzero (independently). These use the normal export
coordinate conversion and Qt Euler angles in degrees, not the controlled parent's
transform. Explicit `self.initialPosition` and `self.initialRotation` custom
properties override these generated values.

`Qml.AnimatedGauge` likewise exports its EMPTY's nonzero local position as
`initialOffset`, with the normal coordinate conversion. `self.initialOffset`
overrides the generated value.
Internally, `export_shipmate(obj, context)` receives a typed, immutable
`ShipmateExportContext` containing the node ID, indentation depth, parent ID,
object-name flag, and coordinate-conversion flag.
The same context is passed unchanged to every `export_qml_*` helper; its
definition lives in `shipmate/qt_export_context.py` to avoid circular imports.
These initial values are read directly from the EMPTY's Transform location and
rotation, independently of parent transforms and collection offsets. Components
below `1e-5` are treated as zero when deciding whether to emit them.

Shipmate EMPTY markers recursively export their Blender children inside their
QML component block. For example, parent a `Qml.HoverableMatSwitcher` EMPTY to
a `Qml.Rheostat` EMPTY to nest `LM.HoverableMaterialSwitcher` inside
`LM.RheostatButton`. Hidden-render children and their subtrees remain excluded.

**Add → Shipmate → Qml.NodeSwitcher** creates an EMPTY exported as
`LM.NodeSwitcher { view: parent }`, including when nested beneath another
Shipmate marker or inside a linked collection. Manually authored
`qml_type = QML.NodeSwitcher` is also recognized. Use `self.activated` for the
activation value or binding, and `self.view` to override the default target.
Other custom properties follow the object-property rules above.

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
- **LOD:** generated levels (**Generate LODs**) are made like Qt's importer
  (`qt_simplifier.py`): meshoptimizer's edge collapse on each material subset, with
  the weld, level targets and normal recalculation of `generateMeshLevelsOfDetail`.
  **LOD Levels** sets the highest level kept. With **Camera Distance LODs** off,
  generated level distances use `error × scaleFactor`, in mesh-local units.
  Enable **Use meshoptimizer** to select the optional `meshoptimizer` Python
  bindings instead. It simplifies each material subset to half the preceding
  triangle-count target per level and uses camera distance ranges for LOD transitions.
  The package must be installed into Blender's Python environment. This backend
  does not use **Keep Vertex Caps**.
  Qt scales the stored distance by the model scale and `levelOfDetailBias`,
  so it is not a scene distance. With **Recalculate LOD Normals**
  off, vertices are welded by position and normal, so flat-shaded meshes may get no levels.
  Simplification is pure Python and can be slow on large meshes. Inspect results
  for holes or popping before enabling it in production. Hand-picked LODs are not
  generated; see [Manual LODs](#manual-lods).
- **LOD normals:** with **Recalculate LOD Normals**, generated LODs get rebuilt
  normals like Qt's importer does with `recalculateLodNormals`. **Merge Angle**
  and **Split Angle** (degrees, 0–270) are `recalculateLodNormalsMergeAngle` and
  `recalculateLodNormalsSplitAngle`. A vertex whose normal changes past the split
  angle is duplicated and appended after LOD0's vertices.
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

## Manual LODs

Select a mesh object and open **Properties → Object Constraints → Qt Quick 3D LOD**.
Enable **LOD Overrides**, then assign mesh objects to the LOD1–LOD7 fields.
These are per-object exporter settings, not a Blender transform constraint.
When the panel is disabled or export **Manual LODs** is off, all panel overrides
are ignored and generation uses the global export settings.

Enable **Override Generated LOD Levels** to cap generation at the lower of
**Maximum Generated LOD** and global **LOD Levels**. Set it to `0` to disable
generation for the object. Explicit manual levels above the cap remain available;
gaps retain previous geometry. An unchecked cap uses the global setting.

By default, LOD distances are calculated from the [camera ranges](#lod-camera-ranges).
When **Camera Distance LODs** is off, manual levels use the same geometric-error
distances that automatic simplification of LOD0 would produce. This requires
running the simplifier even for a manual-only export. If it cannot produce a
corresponding level for a subset, the exporter uses the same level's distance
from the largest LOD0 subset (by index count). If that subset also lacks the
level, it uses the camera range and reports a warning; distances remain
nondecreasing. To override camera ranges, check individual **Camera Distance
Overrides** fields and enter camera-to-bounding-box surface depths in scene units.
Unchecked levels follow the global **Camera Distance LODs** setting. Values are converted to Qt mesh
distances using the reference camera below.
If an override or fallback is smaller than the preceding level's depth, it is
clamped to that depth with a warning, so those levels may switch together.
**Distance Scale** divides the converted values; its default of 1 preserves the target depths.

The old `mesh_lod1`–`mesh_lod7`, `mesh_lods_max` and `mesh_lods_distances`
custom properties are no longer read. Existing files must be configured in the
new panel; mesh datablocks formerly used as LOD sources need mesh objects.

The object's own mesh is LOD0. Each assigned mesh is appended to LOD0's vertex
buffer in the same `.mesh` file, so Qt Quick 3D switches LODs without loading
another file. The `.mesh` is named `_MLODs.mesh` when manual LODs are embedded.

- Each LOD triangle keeps the material of the LOD0 subset with the same material
  slot index. If a level has no triangles for a subset, that subset retains its
  previous geometry. Trailing missing levels are omitted; gaps before a later
  level repeat the previous range to preserve Qt's positional LOD numbering.
  Triangles that use a slot LOD0 does not have are dropped with a warning.
- The LOD mesh must have the same vertex attributes as LOD0, such as a second UV
  set (UV1) or vertex colors. A mismatched LOD is skipped with a warning rather
  than padded.
- Levels are stored by position, so the exporter writes every level from LOD1 up
  to the highest one in use. If LOD1 is not set but LOD2 is, LOD1
  repeats LOD0's triangles at LOD2's distance, so Qt never picks it early, and LOD2 is
  the LOD2 mesh. Levels
  above the highest one in use are not written.
- Meshes are read in local space and use the **Apply Modifiers** and **Convert
  Coordinates** options like LOD0. Cloth objects do not get manual LODs.
- A source that points to the object's own mesh is ignored with a warning.
- Manual LODs and **Generate LODs** can be used together. Each level uses its
  LOD object if one is set and valid. Generate LODs fills every other level
  (LOD1–LOD7). If a manual LOD object is skipped, the
  generated level for that number is used instead, and a warning is shown.
- Turning **Manual LODs** off ignores manual meshes and their custom distances.
  Turning **Generate LODs** off with Manual LODs on keeps only the manual levels.

### LOD camera ranges

The fixed `LOD_CAMERA_RANGES` in `qt_mesh_writer.py` specifies camera-to-subset-bounding-box
surface depths in scene units: 500, 2,000, 5,000, 10,000, 20,000, 50,000 and 100,000
for LOD1–LOD7 respectively. These can be adjusted in that array.

For each subset and level, the stored Qt value is estimated as
`target_surface_depth * 2 * tan(60° / 2) / 1080`.
This is calibrated for a 60° vertical-FOV perspective camera, a 1080-pixel-high
renderer viewport, camera and model LOD biases of 1, **Distance Scale** 1,
unit model scale. Set the camera's
`clipFar` beyond the desired visible range.

Qt measures depth to the nearest point of the transformed subset's axis-aligned
bounding box along the camera direction, not Euclidean distance to the object
origin or to the actual mesh surface. Subset bounds may differ, and
rotation, non-unit scale, viewport size, FOV, biases, instancing, or a different
camera used for LOD selection change the transitions. The exporter cannot guarantee
fixed world-space transitions for differently transformed instances sharing one mesh.

### Checking LOD vertex counts

`qt_mesh_validate.py` prints the vertex and triangle count of LOD0 and of every
embedded LOD level:

```sh
python3 qt_mesh_validate.py assets/meshes/Lib/Cube_MLODs.mesh
```

```text
mesh 1234: vertex buffer holds 29 vertices
  LOD0 (main mesh): 16 vertices, 18 triangles
  LOD1 (distance 0.12): 9 vertices, 8 triangles
  LOD2 (distance 0.21): 4 vertices, 2 triangles
```

Use `--json` to print the full parsed structure instead of the summary.

## Cloth and flags

A mesh with a render-enabled **Cloth** modifier exports as `LM.Flag`, using the
matching Shipmate LogicModule. Its `meshSource` is the actual exported `.mesh`,
with original UVs, material subset order, object transforms and children. Cloth
meshes keep their full topology even when global LOD export is enabled.

The exporter evaluates the rest mesh with Cloth temporarily disabled, while
respecting the Apply Modifiers option for modelling modifiers. It restores the
modifier visibility afterwards. Runtime wind animates the exported geometry;
it does not replay Blender's baked cloth simulation or implement self-collision.

The Cloth **Pin Group** is exported with graded weights. The vertex color alpha
stream stores these weights for cloth meshes; both UV sets and vertex RGB remain
available. With no pin group, the inferred pole edge is fixed. The cloth frame
is inferred from geometry and the pinned edge. Cloth subsets reference named `LM.FlagMaterial` variants directly, for example
`mat_AmericanFlag_BalaoBridge_flag`. Each variant references the original material
through `sourceMaterial`, and stores immutable cloth frame and pin settings.
`check_asset_library.rb` moves both declarations to `MaterialsLibrary.qml`, tracks
the dependency, and upgrades older `LM.Flag` references automatically. Different
cloth profiles get distinct variants; identical profiles can share one material.
No material Instantiator or per-Flag material wrapper is required. Textures
(including UV transforms), base color, roughness and metalness come from the
source material. Wind direction is computed per rendered model in the shader.

Wind normally follows **Environment → Wind / flags**. Optional numeric object
custom properties `windStrength` (m/s), `windDirection` (world degrees, 0 = +X,
90 = +Z), and `phase` override the shared settings. Give the cloth sufficient
subdivision for smooth waves; export does not invent extra vertices.

Regression test (factory startup does not open or modify your working blend):

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python tests/test_cloth_export.py
```

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


### Rheostat and hatch movement sounds

The QML Rheostat panel has an optional **Sequential Mode** checkbox (`sequentialMode`,
false by default). When enabled, the generated control waits for each physical position
before accepting the next scroll step.

Both QML Rheostat and QML Hatch panels have **Step Sound** (`stepSound`). Leave it empty
to export the original silent control. A filled value generates a `SpatialSound` that
loops only during the movement animation and stops when movement ends or the control
is destroyed. Existing output/validator handlers are preserved.

Use a QRC URL such as `qrc:/sounds/lever.wav`, a URL relative to the generated QML, or a
local audio file. Blender-relative `//` paths and absolute file paths become file URLs;
local files are referenced, not copied into the export. Ensure QRC sounds are included
in your application resources. SpatialAudio imports are added only when used.

Sound follows the exported control's node `scenePosition` and `sceneRotation`, including
rigid-body hatch nodes. World pose is used so scaled parents do not transform audio twice.
Existing markers expose the new fields without recreating their Blender objects.


### Blender Speaker objects

Native Blender `SPEAKER` objects now export as `SpatialSound`, without a Qml marker.
The speaker's Node retains its parent, local position, rotation and scale; the sound
tracks its world pose separately so parent transforms are applied once. Speaker children,
collection instances and render visibility use the ordinary scene export rules.

Speakers use Qt's native `SpatialSound.Logarithmic` attenuation; no manual JavaScript
attenuation is generated. `size` comes from Blender reference distance and the Node's
world scale. Finite maximum distance becomes the hard cutoff; Blender's unbounded
default uses 100 times the source size. Both distances are in exported world units.
Blender rolloff, volume limits and cone values remain metadata, not custom attenuation.

Speaker audio files (including packed sounds) are copied into `sounds/`, deduplicated,
and included in the generated QRC, CMake resource list and export manifest. Empty speakers
still export and can receive a source at runtime. Missing files produce an export warning.

Optional custom properties on a Speaker: `autoPlay` (default true) and `loops` (default 1;
use -1 for continuous ambience). These are runtime defaults, not Blender NLA scheduling.
Qt SpatialSound has no pitch property: Blender pitch is retained as `blenderPitch`, with
a warning when it is not 1. NLA audio strip timing is not exported and produces a warning.
Location/rotation animation can use the exported speaker Node like other scene objects.

A Speaker may define a string custom property `controller` containing a QML expression,
for example `root.engineController`. The exported sound declares
`property var controller: root.engineController` and listens for `soundChanged`.
The controller's `sound` value supplies `play` (boolean) and `volume` (intensity 0–1).
Initial state and controller replacement are synchronized too; changing volume while
playing does not restart the sound. Replace `sound` or emit `soundChanged` when its
fields change. Without a controller, the existing playback defaults apply.

A controller can also be the sound QObject itself (for example
`cubicleModel_.motorSound`), exposing `play` and `volume` directly. The exporter listens
to its `playChanged` and `volumeChanged` signals, including when supplied as
`controller.sound`. Controller-driven sounds disable autoplay and synchronize on load.

### Qml.PropertyAnimation

Choose **Add → Shipmate → Qml.PropertyAnimation**, then parent the marker to the mesh
or Empty you want to animate. Edit it in **Object Properties → QML Property Animation**.
The implementation lives in `shipmate/qt_property_animation.py`.

- `property` / `properties`: property name or comma-separated names (quoted in QML).
- `duration`, `from`, `to`: raw QML expression strings; no quotes are added.
  For example, `control_.duration` or `Qt.vector3d(target.eulerRotation.x, target.eulerRotation.y, 360.)`.
- Easing dropdown: all Qt Quick easing types, plus amplitude, overshoot, period and
  an optional raw Bezier curve list such as `[0.25, 0.1, 0.25, 1, 1, 1]`.
- `loops`: -1 exports `Animation.Infinite`; other values export as numbers.
- `running`: exports a boolean; default false.

The generated `LM.PropertyAnimation` always uses `target: parent`. Since Qt animations
do not expose a parent property, a readonly `parent` reference explicitly identifies
the Blender parent; only scene objects hosting an animation receive an extra QML ID.
An unparented marker targets the exported component root. QML expressions are passed
through unchanged and must refer to identifiers available in the receiving component.

### Optional object names

**Include → Object Names** is enabled by default. Disable it to omit every generated
`objectName` declaration, including scene roots, collection components, materials,
never-mirror wrappers, sounds and Shipmate controls. QML IDs and property bindings
remain intact; raw QML expressions are not rewritten.

Python operator usage:

```python
bpy.ops.export_scene.qt_balsam(filepath="/path/to/Scene.qml", with_object_name=False)
```

For direct exporter use, set `settings.with_object_name = False` or pass
`BalsamExporter(filepath, settings, with_object_name=False)`. Missing settings keep
the default enabled behavior.
