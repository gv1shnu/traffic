"""Render a simulated traffic scenario as fixed-CCTV video frames in Blender.

Run inside Blender (headless):

    blender --background --factory-startup --python scripts/sim3d/blender_scene.py -- \
        --trajectories storage/sim3d/stalled_car/trajectories.json \
        --out storage/sim3d/stalled_car [--frames 0:50] [--samples 16]

Everything in the scene is procedural: an Indian two-lane street with painted
kerbs, footpaths, shopfronts, trees, a signal, and procedurally modelled cars,
autorickshaws, motorcycles with riders, buses, trucks and pedestrians. No
third-party assets are required.

Outputs, in --out:
  frames/000000.jpg ...  rendered frames
  ground_truth.json      per-frame projected 2D boxes with ray-cast visibility,
                         the camera model and image-space lane regions

The boxes in ground_truth.json are for evaluation only. They are never shown as
detections; detections come from running the real pipeline on the rendered video.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets as asset_io  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

WIDTH, HEIGHT = 960, 540
CAMERA_POS = (-4.6, 0.0, 6.5)
CAMERA_TARGET = (0.0, 32.0, 0.0)
CAMERA_LENS = 30.0
ANIMATION_FPS = 24
ASSET_DIR = REPO / "storage" / "assets" / "glbs"
RIDER_YAW = 0.0

# --------------------------------------------------------------------------
# Materials


_MATS: dict[str, bpy.types.Material] = {}


def mat(name, color, rough=0.5, metal=0.0, coat=0.0, emission=None, strength=0.0, alpha=1.0):
    key = f"{name}"
    if key in _MATS:
        return _MATS[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Coat Weight"].default_value = coat
    if emission is not None:
        p.inputs["Emission Color"].default_value = (*emission, 1.0)
        p.inputs["Emission Strength"].default_value = strength
    if alpha < 1.0:
        p.inputs["Alpha"].default_value = alpha
    _MATS[key] = m
    return m


def noisy_mat(name, color_a, color_b, scale, rough=0.85, bump=0.15):
    """A procedural material mixing two colours through noise (asphalt, concrete)."""
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = rough
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 8.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*color_a, 1)
    ramp.color_ramp.elements[1].color = (*color_b, 1)
    bump_node = nt.nodes.new("ShaderNodeBump")
    bump_node.inputs["Strength"].default_value = bump
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], p.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump_node.inputs["Height"])
    nt.links.new(bump_node.outputs["Normal"], p.inputs["Normal"])
    _MATS[name] = m
    return m


ENV = REPO / "storage" / "assets" / "polyhaven"


def _image(nt, path, colour=True):
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    if not colour:
        node.image.colorspace_settings.name = "Non-Color"
    node.projection = "BOX"
    node.projection_blend = 0.25
    return node


def tex_mat(name, texture, tile_m, tint=(1.0, 1.0, 1.0), fallback=None):
    """Poly Haven PBR texture with box projection in object space, tiled every tile_m."""
    folder = ENV / "textures" / texture
    if not (folder / "Diffuse.jpg").exists():
        return fallback
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile_m,) * 3
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    diff = _image(nt, folder / "Diffuse.jpg")
    rough = _image(nt, folder / "Rough.jpg", colour=False)
    nor = _image(nt, folder / "nor_gl.jpg", colour=False)
    for n in (diff, rough, nor):
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(diff.outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = (*tint, 1)
    nt.links.new(mix.outputs["Result"], p.inputs["Base Color"])
    nt.links.new(rough.outputs["Color"], p.inputs["Roughness"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], p.inputs["Normal"])
    _MATS[name] = m
    return m


def facade_mat(name, wall, glass=(0.05, 0.07, 0.09)):
    """Building wall with a grid of windows from a brick texture."""
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.offset = 0.0
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Brick Width"].default_value = 1.6
    brick.inputs["Row Height"].default_value = 3.0
    brick.inputs["Mortar Size"].default_value = 0.55
    brick.inputs["Color1"].default_value = (*glass, 1)
    brick.inputs["Color2"].default_value = (*glass, 1)
    brick.inputs["Mortar"].default_value = (*wall, 1)
    plaster = ENV / "textures" / "concrete_wall_006" / "Diffuse.jpg"
    if plaster.exists():
        img = _image(nt, plaster)
        pmap = nt.nodes.new("ShaderNodeMapping")
        pmap.inputs["Scale"].default_value = (0.25, 0.25, 0.25)
        nt.links.new(coord.outputs["Object"], pmap.inputs["Vector"])
        nt.links.new(pmap.outputs["Vector"], img.inputs["Vector"])
        tinted = nt.nodes.new("ShaderNodeMix")
        tinted.data_type = "RGBA"
        tinted.blend_type = "MULTIPLY"
        tinted.inputs["Factor"].default_value = 1.0
        nt.links.new(img.outputs["Color"], tinted.inputs["A"])
        tinted.inputs["B"].default_value = (*[min(1.0, c * 1.5) for c in wall], 1)
        nt.links.new(tinted.outputs["Result"], brick.inputs["Mortar"])
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    mapping.inputs["Rotation"].default_value = (math.pi / 2, 0, 0)
    nt.links.new(mapping.outputs["Vector"], brick.inputs["Vector"])
    nt.links.new(brick.outputs["Color"], p.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(brick.outputs["Fac"], rough.inputs["Value"])
    rough.inputs["To Min"].default_value = 0.15
    rough.inputs["To Max"].default_value = 0.9
    nt.links.new(rough.outputs["Result"], p.inputs["Roughness"])
    _MATS[name] = m
    return m


# --------------------------------------------------------------------------
# Geometry helpers


def _link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _finish(bm, name, material, parent=None, smooth=True, bevel=0.0, segments=2):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    if bevel > 0:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
        mod.harden_normals = True
    return _link(obj, parent)


def box(name, size, loc, material, parent=None, bevel=0.0, rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Euler(rot).to_matrix(), verts=bm.verts)
    bmesh.ops.translate(bm, vec=loc, verts=bm.verts)
    return _finish(bm, name, material, parent, smooth=bevel > 0, bevel=bevel)


def profile(name, points_yz, width, material, parent=None, x=0.0, bevel=0.05):
    """Extrude a side profile (y forward, z up) across the X axis."""
    bm = bmesh.new()
    left = [bm.verts.new((x - width / 2, y, z)) for y, z in points_yz]
    right = [bm.verts.new((x + width / 2, y, z)) for y, z in points_yz]
    bm.faces.new(list(reversed(left)))
    bm.faces.new(right)
    n = len(points_yz)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([left[i], left[j], right[j], right[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _finish(bm, name, material, parent, smooth=True, bevel=bevel, segments=3)


def cylinder(name, radius, depth, loc, material, parent=None, axis="x", segments=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=depth
    )
    if axis == "x":
        bmesh.ops.rotate(
            bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"), verts=bm.verts
        )
    elif axis == "y":
        bmesh.ops.rotate(
            bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"), verts=bm.verts
        )
    obj = _finish(bm, name, material, parent, smooth=True)
    obj.location = loc
    return obj


def sphere(name, radius, loc, material, parent=None, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=radius)
    bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    obj = _finish(bm, name, material, parent, smooth=True)
    obj.location = loc
    return obj


def text_plate(name, text, loc, rot_z, parent, bg, fg=(0.02, 0.02, 0.02), size=(0.52, 0.13)):
    plate = box(f"{name}_plate", (size[0], 0.02, size[1]), loc, mat(f"plate_{bg}", bg, 0.4), parent)
    plate.rotation_euler = (0, 0, rot_z)
    curve = bpy.data.curves.new(f"{name}_text", "FONT")
    curve.body = text
    curve.size = size[1] * 0.62
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.extrude = 0.002
    txt = bpy.data.objects.new(f"{name}_text", curve)
    txt.data.materials.append(mat("plate_ink", fg, 0.5))
    _link(txt, plate)
    txt.rotation_euler = (math.pi / 2, 0, 0)
    txt.location = (0, -0.012, 0)
    return plate


# --------------------------------------------------------------------------
# Subjects

PAINTS = [
    (0.85, 0.85, 0.86),  # white (most common in India)
    (0.62, 0.63, 0.65),  # silver
    (0.05, 0.05, 0.06),  # black
    (0.55, 0.06, 0.05),  # red
    (0.08, 0.17, 0.38),  # blue
    (0.35, 0.33, 0.30),  # grey
    (0.55, 0.42, 0.25),  # bronze
]
SKIN = [(0.45, 0.28, 0.18), (0.36, 0.22, 0.14), (0.55, 0.36, 0.24), (0.28, 0.17, 0.11)]
CLOTH = [
    (0.75, 0.75, 0.78),
    (0.1, 0.12, 0.25),
    (0.55, 0.1, 0.12),
    (0.2, 0.35, 0.2),
    (0.85, 0.55, 0.1),
    (0.4, 0.15, 0.4),
    (0.15, 0.15, 0.15),
    (0.6, 0.5, 0.35),
]

RUBBER = None
GLASS = None
LIMBS: dict[str, list] = {}


def shared_mats():
    global RUBBER, GLASS
    RUBBER = mat("rubber", (0.02, 0.02, 0.02), 0.8)
    GLASS = mat("glass", (0.02, 0.025, 0.03), 0.05, coat=1.0)


def wheel(root, name, radius, width, loc, hub=(0.6, 0.6, 0.62)):
    pivot = bpy.data.objects.new(f"{name}_pivot", None)
    _link(pivot, root)
    pivot.location = loc
    cylinder(f"{name}_tyre", radius, width, (0, 0, 0), RUBBER, pivot)
    cylinder(
        f"{name}_hub",
        radius * 0.6,
        width + 0.02,
        (0, 0, 0),
        mat("hub", hub, 0.3, 0.9),
        pivot,
        segments=10,
    )
    pivot["wheel_radius"] = radius
    return pivot


def build_car(root, rng, plate):
    idx = rng.randrange(len(PAINTS))
    paint = mat(f"paint_{idx}", PAINTS[idx], 0.25, 0.4, coat=1.0)
    w = 1.75
    profile(
        "body",
        [
            (-2.08, 0.24),
            (2.05, 0.24),
            (2.12, 0.46),
            (2.02, 0.72),
            (0.85, 0.93),
            (-1.55, 0.96),
            (-2.06, 0.88),
            (-2.12, 0.5),
        ],
        w,
        paint,
        root,
        bevel=0.07,
    )
    profile(
        "cabin",
        [(0.9, 0.9), (-0.05, 1.42), (-1.05, 1.42), (-1.62, 0.93)],
        w * 0.86,
        GLASS,
        root,
        bevel=0.04,
    )
    profile(
        "roof",
        [(-0.02, 1.4), (-1.08, 1.4), (-1.1, 1.5), (-0.06, 1.5)],
        w * 0.84,
        paint,
        root,
        bevel=0.03,
    )
    box("bpillar", (w * 0.875, 0.1, 0.5), (0, -0.55, 1.17), paint, root)
    box("grille", (0.9, 0.05, 0.16), (0, 2.12, 0.55), mat("grille", (0.03, 0.03, 0.03), 0.4), root)
    lamp = mat("headlamp", (0.9, 0.9, 0.85), 0.1, emission=(1, 0.97, 0.9), strength=2.0)
    tail = mat("taillamp", (0.6, 0.02, 0.02), 0.2, emission=(1, 0.05, 0.02), strength=1.5)
    for sx in (-1, 1):
        box("headlight", (0.32, 0.05, 0.11), (sx * 0.6, 2.09, 0.66), lamp, root)
        box("taillight", (0.3, 0.05, 0.12), (sx * 0.62, -2.11, 0.74), tail, root)
        box("mirror", (0.16, 0.08, 0.1), (sx * (w / 2 + 0.06), 0.62, 1.0), paint, root)
    for name, y in (("front", 1.32), ("rear", -1.34)):
        for sx in (-1, 1):
            wheel(root, f"wheel_{name}_{sx}", 0.31, 0.21, (sx * (w / 2 - 0.12), y, 0.31))
    text_plate("front", plate, (0, 2.14, 0.4), math.pi, root, (0.95, 0.95, 0.95))
    text_plate("rear", plate, (0, -2.14, 0.45), 0.0, root, (0.95, 0.95, 0.95))


def build_autorickshaw(root, rng, plate):
    green = mat("auto_green", (0.05, 0.32, 0.12), 0.35, coat=0.5)
    yellow = mat("auto_yellow", (0.85, 0.65, 0.04), 0.35, coat=0.5)
    canvas = mat("auto_canvas", (0.03, 0.03, 0.03), 0.8)
    seat = mat("auto_seat", (0.15, 0.05, 0.04), 0.7)
    profile(
        "tub",
        [(-1.45, 0.28), (0.95, 0.28), (0.95, 0.62), (-1.45, 0.62)],
        1.35,
        green,
        root,
        bevel=0.06,
    )
    profile(
        "band",
        [(-1.45, 0.62), (0.95, 0.62), (0.95, 0.9), (-1.45, 0.9)],
        1.35,
        yellow,
        root,
        bevel=0.04,
    )
    profile(
        "nose",
        [(0.9, 0.3), (1.38, 0.34), (1.45, 0.75), (1.2, 1.02), (0.9, 1.02)],
        0.85,
        yellow,
        root,
        bevel=0.08,
    )
    box("windshield", (1.15, 0.04, 0.48), (0, 0.98, 1.27), GLASS, root, rot=(-0.12, 0, 0))
    profile(
        "roof",
        [(1.12, 1.5), (-1.48, 1.52), (-1.48, 1.74), (0.88, 1.76), (1.14, 1.62)],
        1.38,
        canvas,
        root,
        bevel=0.06,
    )
    box("back", (1.36, 0.06, 0.84), (0, -1.45, 1.1), canvas, root)
    for sx in (-1, 1):
        box("pillar", (0.05, 0.05, 0.62), (sx * 0.62, 1.0, 1.2), yellow, root)
        box("pillar_r", (0.05, 0.05, 0.62), (sx * 0.64, -0.2, 1.2), yellow, root)
    box("seat_rear", (1.2, 0.5, 0.4), (0, -1.05, 1.05), seat, root)
    box("seat_front", (0.45, 0.4, 0.25), (0, 0.55, 1.0), seat, root)
    box(
        "headlight",
        (0.18, 0.05, 0.14),
        (0, 1.43, 0.7),
        mat("headlamp", (0.9, 0.9, 0.85), 0.1),
        root,
    )
    wheel(root, "wheel_front", 0.22, 0.13, (0, 1.12, 0.22))
    for sx in (-1, 1):
        wheel(root, f"wheel_rear_{sx}", 0.22, 0.14, (sx * 0.63, -0.95, 0.22))
    text_plate("rear", plate, (0, -1.49, 0.48), 0.0, root, (0.92, 0.78, 0.1), size=(0.42, 0.13))
    # driver
    person_parts(root, rng, seated=True, loc=(0, 0.45, 0.65), scale=0.95)


def build_motorcycle(root, rng, plate):
    idx = rng.randrange(len(PAINTS))
    paint = mat(f"bike_{idx}", PAINTS[idx], 0.3, 0.3, coat=0.8)
    dark = mat("bike_dark", (0.04, 0.04, 0.04), 0.5)
    wheel(root, "wheel_front", 0.3, 0.1, (0, 0.68, 0.3), hub=(0.3, 0.3, 0.3))
    wheel(root, "wheel_rear", 0.3, 0.12, (0, -0.68, 0.3), hub=(0.3, 0.3, 0.3))
    profile(
        "frame",
        [(-0.65, 0.42), (0.45, 0.42), (0.6, 0.75), (0.2, 0.92), (-0.35, 0.82), (-0.75, 0.75)],
        0.26,
        paint,
        root,
        bevel=0.05,
    )
    box("seat", (0.3, 0.7, 0.1), (0, -0.3, 0.88), dark, root, bevel=0.03)
    box("fork", (0.06, 0.06, 0.6), (0, 0.62, 0.62), dark, root, rot=(0.35, 0, 0))
    box("handlebar", (0.7, 0.04, 0.04), (0, 0.5, 1.05), dark, root)
    box(
        "headlight",
        (0.16, 0.1, 0.12),
        (0, 0.72, 0.92),
        mat("headlamp", (0.9, 0.9, 0.85), 0.1),
        root,
    )
    text_plate("rear", plate, (0, -0.9, 0.62), 0.0, root, (0.95, 0.95, 0.95), size=(0.3, 0.16))
    person_parts(root, rng, seated=True, loc=(0, -0.25, 0.85), scale=1.0, helmet=True)


def build_bus(root, rng, plate):
    colours = [
        ((0.75, 0.1, 0.08), (0.9, 0.9, 0.88)),
        ((0.1, 0.3, 0.6), (0.9, 0.9, 0.88)),
        ((0.1, 0.45, 0.2), (0.85, 0.8, 0.5)),
    ]
    a, b = colours[rng.randrange(len(colours))]
    lower = mat(f"bus_lower_{a}", a, 0.35, coat=0.6)
    upper = mat(f"bus_upper_{b}", b, 0.35, coat=0.6)
    box("lower", (2.55, 11.0, 1.2), (0, 0, 0.95), lower, root, bevel=0.08)
    box("windows", (2.5, 10.8, 1.15), (0, 0, 2.12), GLASS, root, bevel=0.05)
    box("upper", (2.55, 11.0, 0.5), (0, 0, 2.95), upper, root, bevel=0.1)
    for k in range(7):
        box("pillar", (2.56, 0.12, 1.15), (0, -5.0 + k * 1.6, 2.12), upper, root)
    box(
        "board",
        (1.6, 0.05, 0.25),
        (0, 5.51, 2.85),
        mat("board", (0.1, 0.05, 0), 0.4, emission=(1, 0.5, 0.05), strength=3),
        root,
    )
    for y in (3.6, -3.4):
        for sx in (-1, 1):
            wheel(root, f"wheel_{y}_{sx}", 0.5, 0.3, (sx * 1.05, y, 0.5))
    text_plate("rear", plate, (0, -5.52, 0.6), 0.0, root, (0.92, 0.78, 0.1))


def build_truck(root, rng, plate):
    cab_c = [(0.85, 0.45, 0.05), (0.1, 0.35, 0.6), (0.65, 0.1, 0.1)][rng.randrange(3)]
    cab = mat(f"truck_cab_{cab_c}", cab_c, 0.35, coat=0.6)
    body = mat("truck_body", (0.75, 0.55, 0.12), 0.6)
    box("cab", (2.35, 1.7, 1.9), (0, 2.85, 1.45), cab, root, bevel=0.1)
    box("windshield", (2.1, 0.05, 0.75), (0, 3.71, 1.85), GLASS, root)
    box("chassis", (2.0, 7.4, 0.35), (0, 0, 0.75), mat("dark", (0.05, 0.05, 0.05), 0.6), root)
    box("cargo", (2.4, 5.5, 2.1), (0, -0.95, 2.0), body, root, bevel=0.04)
    box("cargo_top", (2.3, 5.4, 0.1), (0, -0.95, 3.06), mat("tarp", (0.15, 0.3, 0.55), 0.8), root)
    for y in (2.8, -1.5, -2.7):
        for sx in (-1, 1):
            wheel(root, f"wheel_{y}_{sx}", 0.48, 0.3, (sx * 0.98, y, 0.48))
    back = box(
        "tailgate_sign",
        (1.6, 0.02, 0.35),
        (0, -3.72, 1.6),
        mat("sign_white", (0.9, 0.9, 0.9), 0.5),
        root,
    )
    curve = bpy.data.curves.new("hornok", "FONT")
    curve.body = "HORN OK PLEASE"
    curve.size = 0.2
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    t = bpy.data.objects.new("hornok", curve)
    t.data.materials.append(mat("sign_red", (0.7, 0.05, 0.05), 0.5))
    _link(t, back)
    t.rotation_euler = (math.pi / 2, 0, math.pi)
    t.location = (0, -0.015, 0)
    text_plate("rear", plate, (0, -3.72, 0.75), 0.0, root, (0.92, 0.78, 0.1))


def person_parts(root, rng, seated=False, loc=(0, 0, 0), scale=1.0, helmet=False):
    k_skin, k_shirt, k_pants = (
        rng.randrange(len(SKIN)),
        rng.randrange(len(CLOTH)),
        rng.randrange(len(CLOTH)),
    )
    skin = mat(f"skin_{k_skin}", SKIN[k_skin], 0.6)
    shirt = mat(f"cloth_{k_shirt}", CLOTH[k_shirt], 0.8)
    pants = mat(f"cloth_{k_pants}", CLOTH[k_pants], 0.8)
    hair = mat("hair", (0.02, 0.015, 0.01), 0.6)
    body = bpy.data.objects.new("person", None)
    _link(body, root)
    body.location = loc
    body.scale = (scale, scale, scale)
    hip = 0.0 if seated else 0.9
    profile(
        "torso",
        [
            (-0.11, hip + 0.02),
            (0.11, hip + 0.02),
            (0.12, hip + 0.55),
            (0.08, hip + 0.62),
            (-0.08, hip + 0.62),
            (-0.12, hip + 0.55),
        ],
        0.4,
        shirt,
        body,
        bevel=0.05,
    )
    sphere("head", 0.11, (0, 0.01, hip + 0.78), skin, body, scale=(0.9, 1.0, 1.1))
    if helmet:
        sphere(
            "helmet",
            0.135,
            (0, 0.0, hip + 0.8),
            mat("helmet", (0.05, 0.05, 0.07), 0.2, coat=1),
            body,
        )
    else:
        sphere("hair", 0.115, (0, -0.015, hip + 0.81), hair, body, scale=(0.92, 1.0, 0.85))
    limbs = []
    for sx in (-1, 1):
        arm = bpy.data.objects.new(f"arm_{sx}", None)
        _link(arm, body)
        arm.location = (sx * 0.24, 0, hip + 0.58)
        cylinder("upper_arm", 0.045, 0.55, (0, 0, -0.27), shirt, arm, axis="z", segments=10)
        sphere("hand", 0.045, (0, 0, -0.57), skin, arm)
        leg = bpy.data.objects.new(f"leg_{sx}", None)
        _link(leg, body)
        leg.location = (sx * 0.1, 0, hip + 0.04)
        cylinder("thigh", 0.075, 0.86, (0, 0, -0.43), pants, leg, axis="z", segments=10)
        box("shoe", (0.1, 0.24, 0.07), (0, 0.05, -0.88), mat("shoe", (0.05, 0.04, 0.03), 0.6), leg)
        if seated:
            leg.rotation_euler = (math.radians(80), 0, 0)
            arm.rotation_euler = (math.radians(55), 0, 0)
        limbs.append((arm, leg, sx))
    LIMBS.setdefault(root.name, []).extend(limbs)
    return body


def build_person(root, rng, plate):
    person_parts(root, rng)


# --------------------------------------------------------------------------
# Third-party model library (config/sim3d_assets.json)

COMMERCIAL = {"autorickshaw", "bus", "truck"}
PLATE_Z = {"car": 0.45, "autorickshaw": 0.45, "bus": 0.7, "truck": 0.75, "motorcycle": 0.6}


def hull_points(objs, inv):
    """Convex-hull vertices of a template in root space; enough to project exact 2D boxes."""
    co = asset_io.evaluated_coords(objs)
    m = np.array(inv)
    chunks = [co @ m[:3, :3].T + m[:3, 3]]
    pts = np.unique(np.round(np.vstack(chunks), 3), axis=0)
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in pts]
    result = bmesh.ops.convex_hull(bm, input=verts)
    hull = [Vector(v.co) for v in result["geom"] if isinstance(v, bmesh.types.BMVert)]
    bm.free()
    return hull


class AssetLibrary:
    def __init__(self, manifest: Path, glb_dir: Path):
        self.by_kind: dict[str, list[dict]] = {}
        for a in json.loads(manifest.read_text())["assets"]:
            if (glb_dir / f"{a['uid']}.glb").exists():
                self.by_kind.setdefault(a["kind"], []).append(a)
        self.glb_dir = glb_dir
        self.templates: dict[str, tuple] = {}

    def has(self, kind: str) -> bool:
        return bool(self.by_kind.get(kind))

    def template(self, asset: dict):
        uid = asset["uid"]
        if uid not in self.templates:
            root, objs = asset_io.import_asset(
                self.glb_dir / f"{uid}.glb",
                asset["kind"],
                yaw_deg=asset["yaw_deg"],
                name=f"tpl_{uid[:8]}",
                size=asset.get("length_m"),
            )
            bpy.context.view_layer.update()
            inv = root.matrix_world.inverted()
            hull = hull_points(objs, inv)
            animated = any(o.animation_data and o.animation_data.action for o in objs)
            for o in [root, *root.children_recursive]:
                o.hide_render = True
            root.location = (0, -900, -100)
            self.templates[uid] = (root, hull, animated)
        return self.templates[uid]

    def instance(self, kind: str, rng: random.Random, name: str, static_only=False):
        options = self.by_kind[kind]
        if static_only:
            static = [a for a in options if not self.template(a)[2]]
            options = static or options
        asset = options[rng.randrange(len(options))]
        tpl, hull, _ = self.template(asset)
        mapping = {tpl: tpl.copy()}
        mapping[tpl].name = name
        for o in tpl.children_recursive:
            mapping[o] = o.copy()
        for o, c in mapping.items():
            bpy.context.scene.collection.objects.link(c)
            c.hide_render = False
            if o.parent in mapping:
                c.parent = mapping[o.parent]
                c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
            for mod in c.modifiers:
                if mod.type == "ARMATURE" and mod.object in mapping:
                    mod.object = mapping[mod.object]
        root = mapping[tpl]
        root.location = (0, 0, 0)
        return root, asset, hull


RIDER_UID = "09b82fda6ec54d06b740dfd56660b248"  # "Standing / Sitting Animation", CC BY 4.0
RIDER_COLOURS = [(0.55, 0.08, 0.08), (0.08, 0.15, 0.35), (0.75, 0.75, 0.72), (0.12, 0.3, 0.15)]
_RIDERS: list = []


def rider_material(shirt):
    """Clothing by height on the seated figure: trousers, shirt, skin, dark helmet."""
    m = bpy.data.materials.new(f"rider_{len(_RIDERS)}")
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.7
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    stops = [
        (0.0, (0.1, 0.1, 0.12)),
        (0.42, shirt),
        (0.86, (0.38, 0.24, 0.16)),
        (0.9, (0.03, 0.03, 0.04)),
    ]
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = 0.0, (*stops[0][1], 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = (
        stops[1][0],
        (*stops[1][1], 1),
    )
    for pos, col in stops[2:]:
        e = ramp.color_ramp.elements.new(pos)
        e.color = (*col, 1)
    scale = nt.nodes.new("ShaderNodeMath")
    scale.operation = "DIVIDE"
    scale.inputs[1].default_value = 1.25
    nt.links.new(sep.outputs["Z"], scale.inputs[0])
    nt.links.new(scale.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], p.inputs["Base Color"])
    return m


def rider_templates(glb_dir: Path):
    """Static seated riders baked from frame 0 of the sitting animation."""
    if _RIDERS:
        return _RIDERS
    path = glb_dir / f"{RIDER_UID}.glb"
    if not path.exists():
        return _RIDERS
    scene = bpy.context.scene
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o not in before]
    scene.frame_set(0)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    meshes = []
    for o in objs:
        if o.type == "MESH" and not o.name.startswith("Icosphere"):
            ev = o.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(ev)
            mesh.transform(ev.matrix_world)
            meshes.append(mesh)
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    import bmesh as _bm

    bm = _bm.new()
    for mesh in meshes:
        bm.from_mesh(mesh)
    baked = bpy.data.meshes.new("rider_baked")
    bm.to_mesh(baked)
    bm.free()
    co = np.array([v.co for v in baked.vertices])
    lo, hi = co.min(axis=0), co.max(axis=0)
    centre = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    factor = 1.25 / (hi[2] - lo[2])
    baked.transform(Matrix.Scale(factor, 4) @ Matrix.Translation(-centre))
    for poly in baked.polygons:
        poly.use_smooth = True
    for colour in RIDER_COLOURS:
        mesh = baked.copy()
        mesh.materials.clear()
        mesh.materials.append(rider_material(colour))
        _RIDERS.append(mesh)
    return _RIDERS


def dress(root, kind, asset, hull, rng, plate):
    """Add an Indian-format number plate and, on two-wheelers, a rider."""
    ys = [p.y for p in hull]
    lo_y, hi_y = min(ys), max(ys)
    if plate and kind in PLATE_Z:
        bg = (0.92, 0.78, 0.1) if kind in COMMERCIAL else (0.95, 0.95, 0.95)
        size = (0.3, 0.16) if kind == "motorcycle" else (0.5, 0.12)
        z = PLATE_Z[kind]
        text_plate("rear", plate, (0, lo_y - 0.015, z), 0.0, root, bg, size=size)
        if kind != "motorcycle":
            text_plate("front", plate, (0, hi_y + 0.015, z), math.pi, root, bg, size=size)
    if kind == "motorcycle":
        riders = rider_templates(Path(ASSET_DIR))
        if riders:
            rider = bpy.data.objects.new("rider", riders[rng.randrange(len(riders))])
            _link(rider, root)
            rider.location = (0, -0.2, 0.3)
            rider.rotation_euler = (0, 0, math.radians(RIDER_YAW))
        else:
            person_parts(root, rng, seated=True, loc=(0, -0.15, 0.62), scale=1.0, helmet=True)


BUILDERS = {
    "car": build_car,
    "autorickshaw": build_autorickshaw,
    "motorcycle": build_motorcycle,
    "bus": build_bus,
    "truck": build_truck,
    "person": build_person,
}


# --------------------------------------------------------------------------
# Static environment


def tree_template(height=7.0):
    """Import the Poly Haven jacaranda once as a hidden template (None if absent)."""
    path = ENV / "models" / "jacaranda_tree" / "jacaranda_tree.gltf"
    if not path.exists():
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new("tree_template", None)
    _link(root)
    for o in objs:
        if o.parent is None:
            mw = o.matrix_world.copy()
            o.parent = root
            o.matrix_world = mw
    bpy.context.view_layer.update()
    lo, hi = asset_io.world_bounds(objs)
    root.scale = (height / (hi.z - lo.z),) * 3
    for o in [root, *objs]:
        o.hide_render = True
    root.location = (0, -900, 0)
    return root


def place_tree(template, xy, rng):
    mapping = {template: template.copy()}
    for o in template.children_recursive:
        mapping[o] = o.copy()
    for o, c in mapping.items():
        _link(c)
        c.hide_render = False
        if o.parent in mapping:
            c.parent = mapping[o.parent]
    root = mapping[template]
    s = template.scale[0] * rng.uniform(0.8, 1.1)
    root.scale = (s, s, s)
    root.location = (xy[0], xy[1], 0.0)
    root.rotation_euler = (0, 0, rng.uniform(0, 2 * math.pi))


def build_environment(meta, rng):
    lw = meta["lane_width"]
    road_half = lw
    asphalt = tex_mat(
        "asphalt_tex",
        "asphalt_02",
        5.0,
        (0.75, 0.75, 0.75),
        noisy_mat("asphalt", (0.07, 0.07, 0.075), (0.16, 0.16, 0.16), 40.0, rough=0.9),
    )
    concrete = tex_mat(
        "pavers_tex",
        "concrete_pavers_02",
        2.0,
        (1.0, 0.97, 0.92),
        noisy_mat("pavers", (0.42, 0.4, 0.37), (0.56, 0.54, 0.5), 12.0, rough=0.9, bump=0.3),
    )
    ground = noisy_mat("ground", (0.22, 0.2, 0.15), (0.32, 0.28, 0.2), 3.0)
    white = mat("paint_white", (0.85, 0.85, 0.82), 0.6)
    kerb_y = mat("kerb_yellow", (0.85, 0.7, 0.08), 0.6)
    kerb_b = mat("kerb_black", (0.04, 0.04, 0.04), 0.6)

    box("ground", (400, 500, 0.1), (0, 70, -0.06), ground)
    box("road", (2 * road_half, 320, 0.02), (0, 70, 0.0), asphalt)
    for k in range(-20, 110):
        y = k * 6.0
        box("centre_dash", (0.15, 3.0, 0.005), (0, y, 0.013), white)
    for sx in (-1, 1):
        box("edge_line", (0.12, 320, 0.005), (sx * (road_half - 0.25), 70, 0.013), white)
        box("footpath", (3.2, 320, 0.18), (sx * (road_half + 1.6), 70, 0.09), concrete)
        for k in range(-60, 230):
            y = k * 1.0
            box(
                "kerb",
                (0.2, 1.0, 0.24),
                (sx * (road_half + 0.1), y + 0.5, 0.12),
                kerb_y if k % 2 else kerb_b,
            )
    sig = meta["scenario"].get("signal")
    stop_y = sig["stop_line_y"] if sig else 48.0
    box("stop_line", (road_half, 0.35, 0.005), (-road_half / 2, stop_y, 0.014), white)
    for k in range(8):
        box("zebra", (0.5, 3.0, 0.005), (-road_half + 0.45 + k * 0.9, stop_y + 2.2, 0.014), white)

    # Building frontage on both sides with shop signage.
    walls = [
        (0.82, 0.72, 0.55),
        (0.75, 0.55, 0.45),
        (0.85, 0.82, 0.75),
        (0.6, 0.7, 0.75),
        (0.9, 0.8, 0.55),
        (0.7, 0.75, 0.6),
        (0.8, 0.6, 0.6),
    ]
    signs = [
        (0.8, 0.1, 0.1),
        (0.1, 0.3, 0.7),
        (0.95, 0.75, 0.1),
        (0.1, 0.55, 0.3),
        (0.9, 0.45, 0.1),
    ]
    for sx in (-1, 1):
        y = -30.0
        while y < 200:
            width = rng.uniform(7, 14)
            height = rng.uniform(6, 17)
            depth = 10
            x = sx * (road_half + 3.2 + depth / 2)
            facade = facade_mat(
                f"facade_{rng.randrange(len(walls))}", walls[rng.randrange(len(walls))]
            )
            box("building", (depth, width - 0.6, height), (x, y + width / 2, height / 2), facade)
            sign_mat = mat(
                f"sign_{rng.randrange(len(signs))}", signs[rng.randrange(len(signs))], 0.5
            )
            box(
                "shop_sign",
                (0.15, width * 0.8, 0.9),
                (x - sx * (depth / 2 + 0.1), y + width / 2, 3.4),
                sign_mat,
            )
            box(
                "shutter",
                (0.06, width * 0.7, 2.6),
                (x - sx * (depth / 2 + 0.03), y + width / 2, 1.4),
                mat("shutter", (0.35, 0.36, 0.38), 0.5, metal=0.6),
            )
            y += width

    trunk = mat("bark", (0.18, 0.12, 0.07), 0.9)
    leaves = noisy_mat("leaves", (0.05, 0.16, 0.04), (0.13, 0.3, 0.07), 6.0, rough=0.8, bump=0.6)
    pole = mat("pole", (0.4, 0.4, 0.42), 0.4, metal=0.7)
    tree = tree_template()
    for sx in (-1, 1):
        for k in range(12):
            y = -8 + k * 17 + rng.uniform(-3, 3) + (8 if sx > 0 else 0)
            x = sx * (road_half + 2.7)
            if math.hypot(x - CAMERA_POS[0], y - CAMERA_POS[1]) < 12:
                continue  # keep the camera mast clear of foliage
            if sx < 0 and y < 60:
                continue  # near-side canopy would hang across the camera's view of the lane
            if tree is not None:
                place_tree(tree, (x, y), rng)
                continue
            cylinder("trunk", 0.18, 4.5, (x, y, 2.25), trunk, axis="z", segments=8)
            for _ in range(3):
                sphere(
                    "canopy",
                    rng.uniform(1.4, 2.0),
                    (x + rng.uniform(-0.8, 0.8), y + rng.uniform(-0.8, 0.8), rng.uniform(4.6, 5.6)),
                    leaves,
                    scale=(1, 1, 0.75),
                )
    for sx in (-1, 1):
        for k in range(8):
            y = 12 + k * 28 + (14 if sx > 0 else 0)
            x = sx * (road_half + 0.5)
            cylinder("lamp_pole", 0.08, 8.0, (x, y, 4.0), pole, axis="z", segments=8)
            box("lamp_arm", (1.5, 0.12, 0.08), (x - sx * 0.7, y, 7.9), pole)

    # Traffic signal on the near-side footpath at the stop line.
    sx = -1
    x = sx * (road_half + 0.6)
    cylinder(
        "signal_pole",
        0.09,
        4.2,
        (x, stop_y, 2.1),
        mat("signal_pole", (0.2, 0.2, 0.2), 0.5),
        axis="z",
    )
    head = box(
        "signal_head",
        (0.35, 0.3, 1.0),
        (x, stop_y - 0.05, 4.6),
        mat("signal_body", (0.05, 0.05, 0.05), 0.5),
    )
    lamps = {}
    for name, z, colour in (
        ("red", 0.3, (1, 0.05, 0.02)),
        ("amber", 0.0, (1, 0.6, 0.0)),
        ("green", -0.3, (0.1, 1, 0.3)),
    ):
        m = bpy.data.materials.new(f"signal_{name}")
        m.use_nodes = True
        p = m.node_tree.nodes["Principled BSDF"]
        p.inputs["Base Color"].default_value = (*[c * 0.2 for c in colour], 1)
        p.inputs["Emission Color"].default_value = (*colour, 1)
        p.inputs["Emission Strength"].default_value = 0.0
        sphere(f"signal_{name}", 0.12, (0, -0.17, z), m, head)
        lamps[name] = p
    return lamps


def setup_world(rng):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("sky")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes["Background"]
    hdri = ENV / "hdri" / "kloofendal_48d_partly_cloudy_puresky.hdr"
    if hdri.exists():
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(str(hdri))
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 1.0
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.sky_type = "NISHITA"
        sky.sun_elevation = math.radians(38)
        sky.sun_rotation = math.radians(140)
        sky.altitude = 900
        sky.air_density = 1.2
        sky.dust_density = 2.5
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.16

    cam_data = bpy.data.cameras.new("cctv")
    cam_data.lens = CAMERA_LENS
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("cctv", cam_data)
    _link(cam)
    cam.location = CAMERA_POS
    direction = Vector(CAMERA_TARGET) - Vector(CAMERA_POS)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 92
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = -0.2
    scene.render.use_persistent_data = True
    scene.render.fps = ANIMATION_FPS
    return cam


# --------------------------------------------------------------------------
# Projection and ground truth


def project(scene, cam, point):
    v = world_to_camera_view(scene, cam, Vector(point))
    return v.x * WIDTH, (1.0 - v.y) * HEIGHT, v.z


def clip_polygon(points):
    """Clip an image-space polygon to the frame (Sutherland-Hodgman)."""

    def clip(poly, inside, intersect):
        out = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
        return out

    def ix(a, b, x):
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def iy(a, b, y):
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    poly = list(points)
    for inside, inter in (
        (lambda p: p[0] >= 0, lambda a, b: ix(a, b, 0)),
        (lambda p: p[0] <= WIDTH, lambda a, b: ix(a, b, WIDTH)),
        (lambda p: p[1] >= 0, lambda a, b: iy(a, b, 0)),
        (lambda p: p[1] <= HEIGHT, lambda a, b: iy(a, b, HEIGHT)),
    ):
        if not poly:
            break
        poly = clip(poly, inside, inter)
    return poly


def lane_regions(scene, cam, meta):
    lw = meta["lane_width"]
    y0, y1 = 2.0, 95.0
    out = []
    for rid, name, x0, x1, sign in (
        ("near_lane", "Near lane (away from camera)", -lw, 0.0, 1),
        ("far_lane", "Oncoming lane", 0.0, lw, -1),
    ):
        corners = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        pts = [project(scene, cam, c)[:2] for c in corners]
        poly = clip_polygon(pts)
        mid = (x0 + x1) / 2
        a = project(scene, cam, (mid, 20.0, 0))
        b = project(scene, cam, (mid, 40.0, 0))
        dx, dy = (b[0] - a[0]) * sign, (b[1] - a[1]) * sign
        norm = math.hypot(dx, dy)
        out.append(
            {
                "id": rid,
                "name": name,
                "polygon": [
                    {
                        "x": round(min(1, max(0, x / WIDTH)), 4),
                        "y": round(min(1, max(0, y / HEIGHT)), 4),
                    }
                    for x, y in poly
                ],
                "direction": [round(dx / norm, 4), round(dy / norm, 4)],
            }
        )
    return out


def local_points(root):
    """Vertices of every mesh under root, in root space (evaluated once)."""
    pts = []
    inv = root.matrix_world.inverted()
    for obj in root.children_recursive:
        if obj.type == "MESH":
            mw = inv @ obj.matrix_world
            pts.extend(mw @ v.co for v in obj.data.vertices)
    return pts


def subject_box(scene, cam, root, pts, depsgraph):
    mw = root.matrix_world
    xs, ys = [], []
    world = [mw @ p for p in pts]
    for w in world:
        x, y, z = project(scene, cam, w)
        if z <= 0:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    full = max(1e-6, (x2 - x1) * (y2 - y1))
    cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(WIDTH, x2), min(HEIGHT, y2)
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    inframe = (cx2 - cx1) * (cy2 - cy1) / full
    # Visibility: ray-cast from the camera to a sample of the subject's vertices.
    origin = cam.matrix_world.translation
    step = max(1, len(world) // 24)
    sample = world[::step]
    hits = 0
    owned = {o.name for o in root.children_recursive}
    for w in sample:
        d = w - origin
        dist = d.length
        ok, loc, _n, _i, obj, _m = scene.ray_cast(
            depsgraph, origin, d.normalized(), distance=dist + 0.05
        )
        if ok and obj is not None and obj.name in owned:
            hits += 1
    return {
        "bbox": [round(cx1, 1), round(cy1, 1), round(cx2, 1), round(cy2, 1)],
        "in_frame": round(inframe, 3),
        "visible": round(hits / max(1, len(sample)), 3),
    }


# --------------------------------------------------------------------------


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--trajectories", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", default="")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--still", action="store_true", help="render only the first selected frame")
    ap.add_argument("--assets", default=str(REPO / "config" / "sim3d_assets.json"))
    ap.add_argument("--asset-dir", default=str(REPO / "storage" / "assets" / "glbs"))
    ap.add_argument("--procedural", action="store_true", help="ignore third-party models")
    ap.add_argument("--camera", default="", help="override camera as x,y,z,tx,ty,tz,lens")
    ap.add_argument(
        "--look", default="", help="override colour management as transform:look:exposure"
    )
    args = ap.parse_args(argv)

    meta = json.loads(Path(args.trajectories).read_text())
    out = Path(args.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)

    global CAMERA_POS, CAMERA_TARGET, CAMERA_LENS
    if args.camera:
        v = [float(x) for x in args.camera.split(",")]
        CAMERA_POS, CAMERA_TARGET, CAMERA_LENS = tuple(v[:3]), tuple(v[3:6]), v[6]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    rng = random.Random(meta["scenario"]["seed"])
    shared_mats()
    cam = setup_world(rng)
    lamps = build_environment(meta, rng)
    if args.look:
        transform, look, exposure = args.look.split(":")
        scene.view_settings.view_transform = transform
        scene.view_settings.look = look or "None"
        scene.view_settings.exposure = float(exposure)
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 2
    scene.cycles.transparent_max_bounces = 2
    scene.cycles.use_fast_gi = True

    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 3.6
    sun.angle = math.radians(1.5)
    sun.color = (1.0, 0.95, 0.88)
    sun_obj = bpy.data.objects.new("sun", sun)
    _link(sun_obj)
    # High afternoon sun, slightly across the street so the carriageway is lit.
    sun_obj.rotation_euler = (math.radians(32), 0, math.radians(-25))

    frames = meta["frames"]
    lo, hi = 0, len(frames)
    if args.frames:
        a, b = args.frames.split(":")
        lo, hi = int(a or 0), int(b or len(frames))
    if args.still:
        hi = lo + 1

    library = None if args.procedural else AssetLibrary(Path(args.assets), Path(args.asset_dir))
    cause_id = meta["truth"].get("cause_agent")
    subjects: dict[int, tuple] = {}
    used_assets: dict[int, str] = {}
    gt_frames = []
    for index in range(lo, hi):
        frame = frames[index]
        seen = set()
        for row in frame["agents"]:
            aid = row["id"]
            seen.add(aid)
            if aid not in subjects:
                agent_rng = random.Random(row["color"])
                if library is not None and library.has(row["kind"]):
                    root, asset, hull = library.instance(
                        row["kind"], agent_rng, f"agent_{aid}", static_only=aid == cause_id
                    )
                    dress(root, row["kind"], asset, hull, agent_rng, row["plate"])
                    used_assets[aid] = asset["uid"]
                    bpy.context.view_layer.update()
                    subjects[aid] = (root, hull)
                else:
                    root = bpy.data.objects.new(f"agent_{aid}", None)
                    _link(root)
                    BUILDERS[row["kind"]](root, agent_rng, row["plate"])
                    bpy.context.view_layer.update()
                    subjects[aid] = (root, local_points(root))
            root, _ = subjects[aid]
            root.location = (row["x"], row["y"], 0.0)
            root.rotation_euler = (0, 0, row["heading"])
            for obj in root.children_recursive:
                obj.hide_render = False
                if "wheel_radius" in obj:
                    obj.rotation_euler = (-row["odometer"] / obj["wheel_radius"], 0, 0)
            if row["kind"] == "person":
                phase = math.sin(row["odometer"] * 2 * math.pi / 1.4) if row["walking"] else 0.0
                for arm, leg, sx in LIMBS.get(root.name, []):
                    leg.rotation_euler = (0.45 * phase * sx, 0, 0)
                    arm.rotation_euler = (-0.35 * phase * sx, 0, 0)
        for aid, (root, _) in subjects.items():
            if aid not in seen:
                for obj in root.children_recursive:
                    obj.hide_render = True
                root.location = (0, -500, -50)
        red = frame.get("signal_red")
        lamps["red"].inputs["Emission Strength"].default_value = 12.0 if red else 0.0
        lamps["green"].inputs["Emission Strength"].default_value = 0.0 if red else 12.0
        scene.frame_set(int(round(frame["t"] * ANIMATION_FPS)) + 1)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        boxes = []
        for row in frame["agents"]:
            root, pts = subjects[row["id"]]
            b = subject_box(scene, cam, root, pts, depsgraph)
            if b is not None:
                boxes.append({"id": row["id"], "kind": row["kind"], "speed": row["speed"], **b})
        gt_frames.append({"index": index, "t": frame["t"], "signal_red": red, "subjects": boxes})
        target = out / "frames" / f"{index:06d}.jpg"
        if not target.exists():  # resumable: keep frames rendered by an earlier run
            scene.render.filepath = str(target)
            bpy.ops.render.render(write_still=True)
        print(f"rendered frame {index} ({len(boxes)} subjects)", flush=True)

    gt = {
        "scenario": meta["scenario"],
        "truth": meta["truth"],
        "fps": meta["fps"],
        "width": WIDTH,
        "height": HEIGHT,
        "camera": {"position": CAMERA_POS, "target": CAMERA_TARGET, "lens_mm": CAMERA_LENS},
        "regions": lane_regions(scene, cam, meta),
        "assets": {str(k): v for k, v in used_assets.items()},
        "frames": gt_frames,
    }
    name = "ground_truth.json" if not args.frames else f"ground_truth_{lo}_{hi}.json"
    (out / name).write_text(json.dumps(gt))


if __name__ == "__main__":
    main()
