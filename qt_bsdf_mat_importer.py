import bpy
import math

# ─────────────────────────────────────────────────────────────────
#  Texture export
# ─────────────────────────────────────────────────────────────────


def save_image(image, img_dir):
    library_name_ = image.library.name if image.library else ''
    safe = sanitize(image.name.replace('.', '_'))
    dest = img_dir / library_name_ / f"{safe}.png"
    old_p = getattr(image, "filepath_raw", "")
    old_f = getattr(image, "file_format", None)

    image.filepath_raw = str(dest)
    image.file_format = 'PNG'
    try:
        out_dir_ = img_dir / library_name_
        out_dir_.mkdir(parents=False, exist_ok=True)
        if getattr(image, "packed_file", None) is not None:
            image.save()
        else:
            image.save_render(filepath=str(dest))
    except Exception:
        try:
            image.save()
        except Exception:
            pass
    finally:
        image.filepath_raw = old_p
        try:
            enum_items = image.bl_rna.properties["file_format"].enum_items.keys(
            )
            if old_f in enum_items:
                image.file_format = old_f
        except Exception:
            pass

    return f"images/{image.library.name}/{safe}.png" if image.library else f"images/{safe}.png"


def sanitize(name: str) -> str:
    import re
    s = re.sub(r'[^A-Za-z0-9_]', '_', name or "")
    return ('_' + s if s and s[0].isdigit() else s) or '_'


def rgba3(c):
    return f"Qt.rgba({c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}, 1.0)"


def rgba4(v):
    a = v[3] if len(v) > 3 else 1.0
    return f"Qt.rgba({v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f}, {a:.6f})"
    # return f"Qt.rgba({v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f}, 1.0)"


def rgb(v):
    return f"Qt.vector3d({v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f})"


def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def _bool(value):
    return "true" if value else "false"


def _vec2(value):
    return f"Qt.vector2d({value[0]:.6f}, {value[1]:.6f})"


def _vec3(value):
    return f"Qt.vector3d({value[0]:.6f}, {value[1]:.6f}, {value[2]:.6f})"


def _mirror_material_preamble(ind1, mirror_info):
    if not mirror_info:
        return []
    return [
        f"{ind1}shipmateMirroredInstance: {_bool(mirror_info['mirrored'])}",
        f"{ind1}shipmateSignedScale: {_vec3(mirror_info['signed_scale'])}",
        f"{ind1}shipmateUvScale: {_vec2(mirror_info['uv_scale'])}",
        f"{ind1}shipmateUvOffset: {_vec2(mirror_info['uv_offset'])}",
    ]


def _qml_number(value):
    value = float(value)
    if math.isfinite(value) and abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return repr(value)


def _texture_property_lines(ind1, prop, src, transform=None):
    if not transform:
        return [
            f'{ind1}{prop}: Texture {{ source: "{src}" }}',
        ]

    lines = [f"{ind1}{prop}: Texture {{"]
    for key in ("pivotU", "pivotV", "positionU", "positionV", "scaleU", "scaleV", "rotationUV"):
        if key in transform:
            lines.append(f"{ind1}    {key}: {_qml_number(transform[key])}")
    if transform.get("generateMipmaps"):
        lines.append(f"{ind1}    generateMipmaps: true")
    if transform.get("mipFilter"):
        lines.append(f"{ind1}    mipFilter: Texture.{transform['mipFilter']}")
    lines.append(f'{ind1}    source: "{src}"')
    lines.append(f"{ind1}}}")
    return lines


def _custom_texture_input_lines(ind1, prop, src, transform=None):
    return _texture_property_lines(ind1, prop, src, transform)


def _first_link(socket):
    if socket and socket.links:
        return socket.links[0]
    return None


def _input_socket(node, *names, index=None):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    if index is not None and len(node.inputs) > index:
        return node.inputs[index]
    return None


def _socket_scalar(socket, default=1.0, visited=None):
    if visited is None:
        visited = set()

    link = _first_link(socket)
    if link:
        return _node_scalar_output(link.from_node, default, visited)

    value = getattr(socket, "default_value", default) if socket else default
    try:
        return float(value)
    except Exception:
        try:
            return float(value[0])
        except Exception:
            return float(default)


def _socket_vec3(socket, default, visited=None):
    if visited is None:
        visited = set()

    link = _first_link(socket)
    if link:
        return _node_vec3_output(link.from_node, default, visited)

    value = getattr(socket, "default_value", None) if socket else None
    if value is None:
        return default

    result = []
    for i in range(3):
        try:
            result.append(float(value[i]))
        except Exception:
            result.append(default[i])
    return tuple(result)


def _is_default(value, default=1.0):
    return abs(float(value) - float(default)) <= 1e-6


def _mul_vec3(a, b):
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


def _div_vec3(a, b):
    return (
        a[0] / b[0] if abs(b[0]) > 1e-9 else a[0],
        a[1] / b[1] if abs(b[1]) > 1e-9 else a[1],
        a[2] / b[2] if abs(b[2]) > 1e-9 else a[2],
    )


def _node_scalar_output(node, default=1.0, visited=None):
    if visited is None:
        visited = set()
    key = ("scalar", id(node))
    if key in visited:
        return float(default)
    visited.add(key)

    if node.type == 'REROUTE':
        return _socket_scalar(_input_socket(node, index=0), default, visited)

    if node.type == 'VALUE':
        output = node.outputs[0] if node.outputs else None
        return _socket_scalar(output, default, visited)

    if node.type == 'MATH':
        op = getattr(node, "operation", "")
        a = _socket_scalar(_input_socket(node, index=0), default, visited)
        b = _socket_scalar(_input_socket(node, index=1), 1.0, visited)
        if op == 'MULTIPLY':
            return a * b
        if op == 'DIVIDE':
            return a / b if abs(b) > 1e-9 else a
        if op == 'ADD':
            return a + b
        if op == 'SUBTRACT':
            return a - b
        return a

    if node.type == 'COMBXYZ':
        return _socket_scalar(_input_socket(node, "X", index=0), default, visited)

    if node.type == 'VECT_MATH':
        vec = _node_vec3_output(node, (default, default, default), visited)
        return vec[0]

    output = node.outputs[0] if node.outputs else None
    value = getattr(output, "default_value", default) if output else default
    try:
        return float(value)
    except Exception:
        try:
            return float(value[0])
        except Exception:
            return float(default)


def _node_vec3_output(node, default=(1.0, 1.0, 1.0), visited=None):
    if visited is None:
        visited = set()
    key = ("vec3", id(node))
    if key in visited:
        return default
    visited.add(key)

    if node.type == 'REROUTE':
        return _socket_vec3(_input_socket(node, index=0), default, visited)

    if node.type == 'VALUE':
        value = _node_scalar_output(node, default[0], visited)
        return (value, value, value)

    if node.type == 'COMBXYZ':
        return (
            _socket_scalar(_input_socket(node, "X", index=0),
                           default[0], visited),
            _socket_scalar(_input_socket(node, "Y", index=1),
                           default[1], visited),
            _socket_scalar(_input_socket(node, "Z", index=2),
                           default[2], visited),
        )

    if node.type == 'VECT_MATH':
        op = getattr(node, "operation", "")
        a = _socket_vec3(_input_socket(node, index=0), default, visited)
        if op == 'SCALE':
            scale = _socket_scalar(_input_socket(
                node, "Scale", index=3), 1.0, visited)
            return (a[0] * scale, a[1] * scale, a[2] * scale)
        b = _socket_vec3(_input_socket(node, index=1),
                         (1.0, 1.0, 1.0), visited)
        if op == 'MULTIPLY':
            return _mul_vec3(a, b)
        if op == 'DIVIDE':
            return _div_vec3(a, b)
        return a

    return default


def _texture_scale_from_vector_socket(socket, visited=None):
    if visited is None:
        visited = set()

    link = _first_link(socket)
    if not link:
        return (1.0, 1.0, 1.0)

    node = link.from_node
    key = ("texture-scale", id(node))
    if key in visited:
        return (1.0, 1.0, 1.0)
    visited.add(key)

    if node.type == 'REROUTE':
        return _texture_scale_from_vector_socket(_input_socket(node, index=0), visited)

    if node.type == 'MAPPING':
        upstream = _texture_scale_from_vector_socket(
            _input_socket(node, "Vector", index=0), visited)
        scale = _socket_vec3(_input_socket(node, "Scale"), (1.0, 1.0, 1.0))
        return _mul_vec3(upstream, scale)

    if node.type == 'VECT_MATH':
        op = getattr(node, "operation", "")
        if op == 'SCALE':
            vector_socket = _input_socket(node, "Vector", index=0)
            upstream = _texture_scale_from_vector_socket(
                vector_socket, set(visited))
            vector_value = _socket_vec3(vector_socket, (1.0, 1.0, 1.0))
            scale = _socket_scalar(_input_socket(node, "Scale", index=3), 1.0)
            return (
                upstream[0] * vector_value[0] * scale,
                upstream[1] * vector_value[1] * scale,
                upstream[2] * vector_value[2] * scale,
            )
        if op == 'MULTIPLY':
            left = _input_socket(node, index=0)
            right = _input_socket(node, index=1)
            upstream = _texture_scale_from_vector_socket(
                left, set(visited))
            upstream = _mul_vec3(
                upstream, _texture_scale_from_vector_socket(right, set(visited)))
            scale = _mul_vec3(
                _socket_vec3(left, (1.0, 1.0, 1.0)),
                _socket_vec3(right, (1.0, 1.0, 1.0)),
            )
            return _mul_vec3(upstream, scale)
        if op == 'DIVIDE':
            left = _input_socket(node, index=0)
            right = _input_socket(node, index=1)
            upstream = _texture_scale_from_vector_socket(
                left, set(visited))
            upstream = _div_vec3(
                upstream, _texture_scale_from_vector_socket(right, set(visited)))
            scale = _div_vec3(
                _socket_vec3(left, (1.0, 1.0, 1.0)),
                _socket_vec3(right, (1.0, 1.0, 1.0)),
            )
            return _mul_vec3(upstream, scale)

    return (1.0, 1.0, 1.0)


def _texture_transform_from_image_node(image_node):
    if not image_node:
        return None

    scale = _texture_scale_from_vector_socket(image_node.inputs.get("Vector"))
    scale_changed = not _is_default(scale[0]) or not _is_default(scale[1])
    if not scale_changed:
        return None

    transform = {
        "scaleU": scale[0],
        "scaleV": scale[1],
        "generateMipmaps": True,
        "mipFilter": "Linear",
    }
    if not _is_default(scale[1]):
        transform["pivotV"] = 1.0
        transform["positionV"] = scale[1] - 1.0
    return transform


def first_linked_image_node(input_socket):
    if not input_socket or not input_socket.links:
        return None
    node = input_socket.links[0].from_node
    if node.type == 'TEX_IMAGE' and node.image:
        return node
    return None


def first_linked_image(input_socket):
    image_node = first_linked_image_node(input_socket)
    if image_node:
        return image_node.image
    return None


def image_node_from_socket_or_chain(sock, visited=None):
    if visited is None:
        visited = set()

    image_node = first_linked_image_node(sock)
    if image_node:
        return image_node

    if not sock or not sock.links:
        return None

    for link in sock.links:
        node = link.from_node
        key = id(node)
        if key in visited:
            continue
        visited.add(key)
        if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
            return node
        for inp in getattr(node, "inputs", []):
            image_node = image_node_from_socket_or_chain(inp, visited)
            if image_node:
                return image_node
    return None


def image_info_from_socket_or_normal_chain(sock):
    image_node = image_node_from_socket_or_chain(sock)
    if not image_node:
        return None, None
    return image_node.image, _texture_transform_from_image_node(image_node)


def image_info_from_normal_input(normal_input):
    nm = find_upstream_node(normal_input, 'NORMAL_MAP')
    if not nm:
        return None, 1., None

    strength = nm.inputs["Strength"].default_value if "Strength" in nm.inputs else getattr(
        nm, "strength", 1.0)
    color_in = nm.inputs.get("Color")
    image_node = first_linked_image_node(color_in)
    if not image_node and color_in:
        image_node = find_upstream_node(color_in, 'TEX_IMAGE')

    if not image_node or not getattr(image_node, "image", None):
        return None, strength, None

    return image_node.image, strength, _texture_transform_from_image_node(image_node)


def image_from_normal_input(normal_input):
    img, strength, _transform = image_info_from_normal_input(normal_input)
    return img, strength


def find_upstream_node(socket, node_type, visited=None):
    if visited is None:
        visited = set()
    if not socket or not socket.links:
        return None
    for link in socket.links:
        node = link.from_node
        key = id(node)
        if key in visited:
            continue
        visited.add(key)
        if node.type == node_type:
            return node
        for inp in node.inputs:
            found = find_upstream_node(inp, node_type, visited)
            if found:
                return found
    return None


def image_from_socket_or_normal_chain(sock):
    img, _transform = image_info_from_socket_or_normal_chain(sock)
    return img


def node_val(node, name, default=None):
    def inp(name):
        return node.inputs.get(name)

    s = inp(name)
    return s.default_value if s is not None else default


def transparent_bsdf_to_quick3d(bsdf, mat, img_dir, exported_images, indent=0, material_id=None, mirror_info=None):
    ind = "    " * indent
    ind1 = "    " * (indent + 1)
    base_color = node_val(bsdf, 'Color', (1.0, 1.0, 1.0, 0.0))
    material_type = "LM.PrincipledBSDFMaterial" if mirror_info else "PrincipledMaterial"
    out = [f"{ind}{material_type} {{",
           f'{ind1}id: {material_id or f"mat_{sanitize(mat.name)}"}',
           f'{ind1}objectName: "{mat.name}"',
           f'{ind1}baseColor: {rgba4(base_color)}',
           # f'{ind1}alphaMode: PrincipledMaterial.Mask',
           # f'{ind1}cullMode: Material.NoCulling',
           f"{ind1}metalness: {mat.metallic:.4f}",
           f"{ind1}roughness: {mat.roughness:.4f}"]
    if mirror_info:
        out += _mirror_material_preamble(ind1, mirror_info)
        out.append(
            f"{ind1}opacity: {base_color[3] if len(base_color) > 3 else 0.0:.6f}")
    else:
        out += [
            f'{ind1}alphaMode: PrincipledMaterial.Blend',
            f'{ind1}depthDrawMode: PrincipledMaterial.OpaquePrePassDepthDraw',
        ]
    out.append(f"{ind}}}")
    return out


def default_to_quick3d(mat, img_dir, exported_images, indent=0, material_id=None, mirror_info=None):
    ind = "    " * indent
    ind1 = "    " * (indent + 1)
    material_type = "LM.PrincipledBSDFMaterial" if mirror_info else "PrincipledMaterial"
    out = [f"{ind}{material_type} {{",
           f'{ind1}id: {material_id or f"mat_{sanitize(mat.name)}"}',
           f'{ind1}objectName: "{mat.name}"',
           f'{ind1}baseColor: {rgba4(mat.diffuse_color)}',
           f'{ind1}cullMode: Material.NoCulling']

    if not mat.use_nodes:
        out += [f"{ind1}metalness: {mat.metallic:.4f}",
                f"{ind1}roughness: {mat.roughness:.4f}"]

    if mirror_info:
        out += _mirror_material_preamble(ind1, mirror_info)
        out.append(
            f"{ind1}opacity: {mat.diffuse_color[3] if len(mat.diffuse_color) > 3 else 1.0:.6f}")
    else:
        out.append(f'{ind1}alphaMode: PrincipledMaterial.Opaque')

    out += [f"{ind}}}"]
    return out


def principled_bsdf_to_quick3d(bsdf, mat, img_dir, exported_images, indent=0, material_id=None, mirror_info=None):
    # if not mat or not mat.use_nodes or not mat.node_tree:
    #    return []

    # bsdf = next((n for n in mat.node_tree.nodes if n.type ==
    #            'BSDF_PRINCIPLED'), None)
    # if not bsdf:
    #    return []

    ind = "    " * indent
    ind1 = "    " * (indent + 1)

    def inp(name):
        return bsdf.inputs.get(name)

    def val(name, default=None):
        s = inp(name)
        return s.default_value if s is not None else default

    def tex_source_from_image(img):
        # library_name_ = img.library.name if img.library else ''
        img_key_ = (
            f"{img.library.name}/{img.name}" if img.library else img.name)
        rel_ = exported_images.get(img_key_) or save_image(img, img_dir)
        exported_images[img_key_] = rel_
        # img.filepath.replace("\\", "/") if img.filepath else img.name
        return rel_

    def texture_info(*socket_names):
        for socket_name in socket_names:
            img, transform = image_info_from_socket_or_normal_chain(
                inp(socket_name))
            if img:
                return img, transform
        return None, None

    material_type = "LM.PrincipledBSDFMaterial" if mirror_info else "PrincipledMaterial"
    lines = [
        f"{ind}{material_type} {{",
        f"{ind1}id: {material_id or f'mat_{sanitize(mat.name)}'}",
        f'{ind1}objectName: "{mat.name}"',
    ]
    if mirror_info:
        lines += _mirror_material_preamble(ind1, mirror_info)

    base_color = val("Base Color", (1.0, 1.0, 1.0, 1.0))
    alpha = float(val("Alpha", 1.0))
    metallic = float(val("Metallic", 0.0))
    roughness = float(val("Roughness", 0.5))
    diffuse_roughness = float(val("Diffuse Roughness", 0.0))
    # emission_color = socket_default(bsdf, "Emission Color", socket_default(bsdf, "Emission", (0.0, 0.0, 0.0, 1.0)))
    emission_color = val("Emission Color", val(
        "Emission", (0.0, 0.0, 0.0, 1.0)))
    emission_strength = float(val("Emission Strength", 1.0))
    transmission = float(val("Transmission Weight", val("Transmission", 0.0)))
    ior = float(val("IOR", 1.5))
    specular_ior_level = float(val("Specular IOR Level", val("Specular", 0.5)))
    specular_tint = val("Specular Tint", (1.0, 1.0, 1.0, 1.0))

    clearcoat = float(val("Coat Weight", val("Clearcoat", 0.0)))
    clearcoat_rough = float(
        val("Coat Roughness", val("Clearcoat Roughness", 0.03)))
    coat_ior = float(val("Coat IOR", 1.5))
    coat_tint = val("Coat Tint", (1.0, 1.0, 1.0, 1.0))
    sheen = float(val("Sheen Weight", val("Sheen", 0.0)))
    sheen_roughness = float(
        val("Sheen Roughness", val("Sheen Roughness", 0.5)))
    sheen_tint = val("Sheen Tint", (1.0, 1.0, 1.0, 1.0))
    anisotropic = float(val("Anisotropic", 0.0))
    anisotropic_rotation = float(val("Anisotropic Rotation", 0.0))
    subsurface = float(val("Subsurface Weight", val("Subsurface", 0.0)))
    subsurface_scale = float(val("Subsurface Scale", 0.1))
    subsurface_radius = val("Subsurface Radius", (1.0, 0.2, 0.1))
    subsurface_ior = float(val("Subsurface IOR", 1.4))
    subsurface_anisotropy = float(val("Subsurface Anisotropy", 0.0))
    thickness = float(val("Thickness", 0.0))
    thin_film_thickness = float(val("Thin Film Thickness", 0.0))
    thin_film_ior = float(val("Thin Film IOR", 1.3))

    base_img, base_transform = texture_info("Base Color")
    metal_img, metal_transform = texture_info("Metallic")
    rough_img, rough_transform = texture_info("Roughness")
    diffuse_rough_img, diffuse_rough_transform = texture_info(
        "Diffuse Roughness")
    specular_img, specular_transform = texture_info(
        "Specular IOR Level", "Specular")
    specular_tint_img, specular_tint_transform = texture_info("Specular Tint")
    anisotropic_img, anisotropic_transform = texture_info("Anisotropic")
    anisotropic_rotation_img, anisotropic_rotation_transform = texture_info(
        "Anisotropic Rotation")
    ao_img, ao_transform = texture_info("Occlusion")
    subsurface_img, subsurface_transform = texture_info(
        "Subsurface Weight", "Subsurface")
    subsurface_scale_img, subsurface_scale_transform = texture_info(
        "Subsurface Scale")
    emissive_img, emissive_transform = texture_info(
        "Emission Color", "Emission")
    emission_strength_img, emission_strength_transform = texture_info(
        "Emission Strength")
    opacity_img, opacity_transform = texture_info("Alpha")
    transmission_img, transmission_transform = texture_info(
        "Transmission Weight", "Transmission")
    thickness_img, thickness_transform = texture_info("Thickness")
    normal_img, normal_strength, normal_transform = image_info_from_normal_input(
        inp("Normal"))

    clearcoat_img, clearcoat_transform = texture_info(
        "Coat Weight", "Clearcoat")
    clearcoat_rough_img, clearcoat_rough_transform = texture_info(
        "Coat Roughness", "Clearcoat Roughness")
    clearcoat_tint_img, clearcoat_tint_transform = texture_info("Coat Tint")
    clearcoat_normal_img, clearcoat_normal_strength, clearcoat_normal_transform = image_info_from_normal_input(
        inp("Coat Normal"))
    sheen_img, sheen_transform = texture_info("Sheen Weight", "Sheen")
    sheen_rough_img, sheen_rough_transform = texture_info("Sheen Roughness")
    sheen_tint_img, sheen_tint_transform = texture_info("Sheen Tint")
    # coat_nm = find_node_upstream(bsdf.inputs.get("Coat Normal"), "NORMAL_MAP")
    # if coat_nm:
    # clearcoat_normal_img = first_image_from_socket(coat_nm.inputs.get("Color"))

    if base_img:
        src = tex_source_from_image(base_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "baseColorMap", src, base_transform)
            lines.append(f"{ind1}baseColor: {rgba4(base_color)}")
        else:
            lines += _texture_property_lines(
                ind1, "baseColorMap", src, base_transform)
    else:
        lines.append(f"{ind1}baseColor: {rgba4(base_color)}")

    lines.append(f"{ind1}metalness: {metallic:.6f}")
    if metal_img:
        src = tex_source_from_image(metal_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "metalnessMap", src, metal_transform)
        else:
            lines += _texture_property_lines(
                ind1, "metalnessMap", src, metal_transform)

    lines.append(f"{ind1}roughness: {roughness:.6f}")
    if rough_img:
        src = tex_source_from_image(rough_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "roughnessMap", src, rough_transform)
        else:
            lines += _texture_property_lines(
                ind1, "roughnessMap", src, rough_transform)

    if mirror_info:
        lines.append(f"{ind1}diffuseRoughness: {diffuse_roughness:.6f}")
        if diffuse_rough_img:
            lines += _custom_texture_input_lines(
                ind1, "diffuseRoughnessMap", tex_source_from_image(diffuse_rough_img), diffuse_rough_transform)

        lines.append(f"{ind1}specularTint: {rgba4(specular_tint)}")
        if specular_img:
            lines += _custom_texture_input_lines(
                ind1, "specularMap", tex_source_from_image(specular_img), specular_transform)
        if specular_tint_img:
            lines += _custom_texture_input_lines(
                ind1, "specularTintMap", tex_source_from_image(specular_tint_img), specular_tint_transform)

        lines.append(f"{ind1}anisotropic: {anisotropic:.6f}")
        if anisotropic_img:
            lines += _custom_texture_input_lines(
                ind1, "anisotropicMap", tex_source_from_image(anisotropic_img), anisotropic_transform)

        lines.append(f"{ind1}anisotropicRotation: {anisotropic_rotation:.6f}")
        if anisotropic_rotation_img:
            lines += _custom_texture_input_lines(
                ind1, "anisotropicRotationMap", tex_source_from_image(anisotropic_rotation_img), anisotropic_rotation_transform)

        lines.append(f"{ind1}subsurfaceWeight: {subsurface:.6f}")
        lines.append(f"{ind1}subsurfaceRadius: {rgb(subsurface_radius)}")
        lines.append(f"{ind1}subsurfaceScale: {subsurface_scale:.6f}")
        lines.append(f"{ind1}subsurfaceIor: {subsurface_ior:.6f}")
        lines.append(
            f"{ind1}subsurfaceAnisotropy: {subsurface_anisotropy:.6f}")
        if subsurface_img:
            lines += _custom_texture_input_lines(
                ind1, "subsurfaceWeightMap", tex_source_from_image(subsurface_img), subsurface_transform)
        if subsurface_scale_img:
            lines += _custom_texture_input_lines(
                ind1, "subsurfaceScaleMap", tex_source_from_image(subsurface_scale_img), subsurface_scale_transform)

    if normal_img:
        src = tex_source_from_image(normal_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "normalMap", src, normal_transform)
            lines.append(f"{ind1}normalStrength: {float(normal_strength):.6f}")
        else:
            lines += _texture_property_lines(
                ind1, "normalMap", src, normal_transform)
            lines.append(f"{ind1}normalStrength: {float(normal_strength):.6f}")

    if ao_img:
        src = tex_source_from_image(ao_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "occlusionMap", src, ao_transform)
        else:
            lines += _texture_property_lines(
                ind1, "occlusionMap", src, ao_transform)

    emissive_rgb = (
        emission_color[0] * (1.0 if mirror_info else emission_strength),
        emission_color[1] * (1.0 if mirror_info else emission_strength),
        emission_color[2] * (1.0 if mirror_info else emission_strength),
    )
    if emissive_img:
        src = tex_source_from_image(emissive_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "emissiveMap", src, emissive_transform)
            lines.append(f"{ind1}emissiveFactor: {rgb(emissive_rgb)}")
        else:
            lines += _texture_property_lines(
                ind1, "emissiveMap", src, emissive_transform)
            lines.append(f"{ind1}emissiveFactor: {rgb(emissive_rgb)}")
    elif any(c > 1e-6 for c in emissive_rgb):
        lines.append(f"{ind1}emissiveFactor: {rgb(emissive_rgb)}")

    if mirror_info:
        lines.append(f"{ind1}emissionStrength: {emission_strength:.6f}")
        if emission_strength_img:
            lines += _custom_texture_input_lines(
                ind1, "emissionStrengthMap", tex_source_from_image(emission_strength_img), emission_strength_transform)

    '''
    if alpha < 0.999:
        lines.append(f"{ind1}opacity: {alpha:.6f}")
        lines.append(f"{ind1}alphaMode: PrincipledMaterial.Blend")
    if opacity_img:
        src = tex_source_from_image(opacity_img)
        lines.append(f'{ind1}opacityMap: Texture {{ source: "{src}" }}')
        if alpha >= 0.999:
            lines.append(f"{ind1}alphaMode: PrincipledMaterial.Blend")

    if not opacity_img and alpha >= 0.999:
        lines.append(f"{ind1}alphaMode: PrincipledMaterial.Opaque")
    '''
    if alpha < 1. or opacity_img:
        lines.append(f"{ind1}opacity: {alpha:.6f}")
        if not mirror_info:
            lines.append(f"{ind1}alphaMode: PrincipledMaterial.Blend")
        # lines.append(f"{ind1}blendMode: PrincipledMaterial.SourceOver")
        # lines.append(f"{ind1}alphaCutoff: 0.5")
        # lines.append(f"{ind1}invertOpacityMapValue: 0.0")
    else:
        if mirror_info:
            lines.append(f"{ind1}opacity: {alpha:.6f}")
        else:
            lines.append(f"{ind1}alphaMode: PrincipledMaterial.Opaque")
        # lines.append(f"{ind1}alphaCutoff: 0.5")
        # lines.append(f"{ind1}invertOpacityMapValue: 0.0")

    if opacity_img:
        opacity_src = tex_source_from_image(opacity_img)
        if mirror_info:
            lines += _custom_texture_input_lines(ind1,
                                                 "opacityMap", opacity_src, opacity_transform)
        else:
            lines += _texture_property_lines(
                ind1, "opacityMap", opacity_src, opacity_transform)
            lines.append(f"{ind1}opacityChannel: PrincipledMaterial.A")

    if transmission > 0.:
        lines.append(f"{ind1}transmissionFactor: {transmission:.6f}")
    # lines.append(f"{ind1}transmissionChannel: PrincipledMaterial.R")

    if transmission_img:
        transmission_src = tex_source_from_image(transmission_img)
        if mirror_info:
            lines += _custom_texture_input_lines(ind1,
                                                 "transmissionMap", transmission_src, transmission_transform)
        else:
            lines += _texture_property_lines(
                ind1, "transmissionMap", transmission_src, transmission_transform)

    if thickness_img:
        thickness_src = tex_source_from_image(thickness_img)
        if mirror_info:
            lines += _custom_texture_input_lines(ind1,
                                                 "thicknessMap", thickness_src, thickness_transform)
        else:
            lines += _texture_property_lines(
                ind1, "thicknessMap", thickness_src, thickness_transform)
    # if transmission > 1e-6:
    #    lines.append(f"{ind1}transmissionFactor: {transmission:.6f}")

    '''
    if clearcoat > 0:
        lines.append(f"{ind1}clearcoatFresnelBias: 0.0")
        lines.append(f"{ind1}clearcoatFresnelPower: 5.0")
        lines.append(f"{ind1}clearcoatFresnelScale: 1.0")
        lines.append(f"{ind1}clearcoatFresnelScaleBiasEnabled: false")
    else:
        lines.append(f"{ind1}clearcoatFresnelBias: 0.0")
        lines.append(f"{ind1}clearcoatFresnelPower: 5.0")
        lines.append(f"{ind1}clearcoatFresnelScale: 1.0")
        lines.append(f"{ind1}clearcoatFresnelScaleBiasEnabled: false")
    '''

    if clearcoat_normal_img:
        clearcoat_normal_src = tex_source_from_image(clearcoat_normal_img)
        if mirror_info:
            lines += _custom_texture_input_lines(ind1,
                                                 "clearcoatNormalMap", clearcoat_normal_src, clearcoat_normal_transform)
            lines.append(
                f"{ind1}clearcoatNormalStrength: {clearcoat_normal_strength}")
        else:
            lines += _texture_property_lines(
                ind1, "clearcoatNormalMap", clearcoat_normal_src, clearcoat_normal_transform)
            lines.append(
                f"{ind1}clearcoatNormalStrength: {clearcoat_normal_strength}")

    lines.append(f"{ind1}clearcoatAmount: {clamp01(clearcoat):.6f}")
    if not mirror_info:
        lines.append(f"{ind1}clearcoatChannel: PrincipledMaterial.R")
    lines.append(
        f"{ind1}clearcoatRoughnessAmount: {clamp01(clearcoat_rough):.6f}")
    if not mirror_info:
        lines.append(f"{ind1}clearcoatRoughnessChannel: PrincipledMaterial.R")
    if mirror_info:
        lines.append(f"{ind1}clearcoatIor: {coat_ior:.6f}")
        lines.append(f"{ind1}clearcoatTint: {rgba4(coat_tint)}")
        if clearcoat_tint_img:
            lines += _custom_texture_input_lines(
                ind1, "clearcoatTintMap", tex_source_from_image(clearcoat_tint_img), clearcoat_tint_transform)

    if clearcoat_img:
        clearcoat_src = tex_source_from_image(clearcoat_img)
        if mirror_info:
            lines += _custom_texture_input_lines(ind1,
                                                 "clearcoatMap", clearcoat_src, clearcoat_transform)
        else:
            lines += _texture_property_lines(
                ind1, "clearcoatMap", clearcoat_src, clearcoat_transform)

    if clearcoat_rough_img:
        clearcoat_rough_src = tex_source_from_image(clearcoat_rough_img)
        if mirror_info:
            lines += _custom_texture_input_lines(
                ind1, "clearcoatRoughnessMap", clearcoat_rough_src, clearcoat_rough_transform)
        else:
            lines += _texture_property_lines(
                ind1, "clearcoatRoughnessMap", clearcoat_rough_src, clearcoat_rough_transform)

    if mirror_info:
        lines.append(f"{ind1}sheenWeight: {sheen:.6f}")
        lines.append(f"{ind1}sheenRoughness: {sheen_roughness:.6f}")
        lines.append(f"{ind1}sheenTint: {rgba4(sheen_tint)}")
        if sheen_img:
            lines += _custom_texture_input_lines(
                ind1, "sheenWeightMap", tex_source_from_image(sheen_img), sheen_transform)
        if sheen_rough_img:
            lines += _custom_texture_input_lines(
                ind1, "sheenRoughnessMap", tex_source_from_image(sheen_rough_img), sheen_rough_transform)
        if sheen_tint_img:
            lines += _custom_texture_input_lines(
                ind1, "sheenTintMap", tex_source_from_image(sheen_tint_img), sheen_tint_transform)

    lines.append(f"{ind1}indexOfRefraction: {ior:.6f}")
    lines.append(f"{ind1}thicknessFactor: {thickness:.6f}")
    if mirror_info:
        lines.append(f"{ind1}thinFilmThickness: {thin_film_thickness:.6f}")
        lines.append(f"{ind1}thinFilmIor: {thin_film_ior:.6f}")

    # spec_amount = max(0.0, min(1.0, specular_ior_level))
    lines.append(f"{ind1}specularAmount: {clamp01(specular_ior_level):.6f}")

    lines.append(f"{ind1}cullMode: Material.NoCulling")
    lines.append(f"{ind}}}")
    return lines


def mat_to_quick3d(mat, img_dir, exported_images, indent=0, material_id=None, mirror_info=None):
    if not mat:
        return []

    if not mat.use_nodes or not mat.node_tree:
        return default_to_quick3d(mat, img_dir, exported_images, indent, material_id, mirror_info)

    nodes_ = []
    for node_ in mat.node_tree.nodes:
        nodes_.append(
            f'// type: {node_.type}, id_name: {node_.bl_idname}, id_name: {node_.bl_label}')

    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return nodes_ + principled_bsdf_to_quick3d(node, mat, img_dir, exported_images, indent, material_id, mirror_info)
        elif node.type == 'BSDF_TRANSPARENT':
            return nodes_ + transparent_bsdf_to_quick3d(node, mat, img_dir, exported_images, indent, material_id, mirror_info)

    # bsdf = next((n for n in mat.node_tree.nodes if n.type ==
            # 'BSDF_PRINCIPLED'), None)
    # if not bsdf:
    return nodes_ + default_to_quick3d(mat, img_dir, exported_images, indent, material_id, mirror_info)
