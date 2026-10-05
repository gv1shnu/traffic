"""Import and normalise third-party glTF assets inside Blender.

Each asset is parented to an empty whose local frame matches the simulator:
+Y is the subject's forward direction, +Z is up, the footprint is centred on the
origin and the lowest vertex rests on z = 0. Assets are scaled to a nominal real-
world size so that heterogeneous downloads share a consistent metric scale.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

# Nominal sizes (metres): vehicles by length, people by height.
NOMINAL = {
    "car": ("length", 4.2),
    "autorickshaw": ("length", 2.75),
    "motorcycle": ("length", 2.0),
    "bus": ("length", 11.0),
    "truck": ("length", 7.4),
    "person": ("height", 1.68),
}


def _mesh_objects(objs):
    return [o for o in objs if o.type == "MESH"]


def evaluated_coords(objs):
    """World-space vertex coordinates of the posed (armature-deformed) meshes."""
    import numpy as np

    depsgraph = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for o in _mesh_objects(objs):
        ev = o.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        if len(mesh.vertices):
            co = np.empty(len(mesh.vertices) * 3)
            mesh.vertices.foreach_get("co", co)
            m = np.array(ev.matrix_world)
            chunks.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
        ev.to_mesh_clear()
    return np.vstack(chunks)


def world_bounds(objs):
    co = evaluated_coords(objs)
    return Vector(co.min(axis=0)), Vector(co.max(axis=0))


def _remove_bone_shapes(objs):
    """Drop the importer's bone display shapes (e.g. 'Icosphere') from the asset."""
    shapes = set()
    for o in objs:
        if o.type == "ARMATURE" and o.pose is not None:
            shapes.update(pb.custom_shape for pb in o.pose.bones if pb.custom_shape)
    for o in objs:
        if o.type == "MESH" and o.name.startswith("Icosphere") and len(o.data.vertices) <= 42:
            shapes.add(o)
    names = {o.name for o in shapes}
    keep = [o for o in objs if o.name not in names]
    for o in shapes:
        bpy.data.objects.remove(o, do_unlink=True)
    return keep


def import_asset(
    path: str | Path, kind: str, yaw_deg: float = 0.0, name: str = "asset", scale=None, size=None
):
    """Import a .glb, normalise it and return (root_empty, imported_objects).

    ``yaw_deg`` rotates the model about Z before normalisation so that its front
    faces +Y; it is recorded per asset in the asset manifest.
    """
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=False)
    objs = _remove_bone_shapes([o for o in bpy.data.objects if o not in before])
    tops = [o for o in objs if o.parent is None or o.parent not in objs]

    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    pivot = bpy.data.objects.new(f"{name}_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.parent = root
    for o in tops:
        mw = o.matrix_world.copy()
        o.parent = pivot
        o.matrix_world = mw
    bpy.context.view_layer.update()

    pivot.rotation_euler = (0, 0, math.radians(yaw_deg))
    bpy.context.view_layer.update()
    lo, hi = world_bounds(objs)
    extent = hi - lo
    if scale is None:
        axis, target = NOMINAL[kind]
        target = size or target
        measured = max(extent.x, extent.y) if axis == "length" else extent.z
        scale = target / max(measured, 1e-6)
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    # Bake: translate to origin, then scale, applied on the pivot.
    pivot.matrix_world = Matrix.Scale(scale, 4) @ Matrix.Translation(-centre) @ pivot.matrix_world
    bpy.context.view_layer.update()
    for o in objs:
        o.hide_render = False
        if o.type == "MESH":
            for m in o.data.materials:
                if m is not None and m.blend_method == "BLEND":
                    m.blend_method = "HASHED"
    # Stop any imported animation from playing unless asked for later.
    for o in objs:
        if o.animation_data is not None:
            o.animation_data.action = o.animation_data.action
    return root, objs


def longest_axis_is_x(objs) -> bool:
    lo, hi = world_bounds(objs)
    return (hi.x - lo.x) > (hi.y - lo.y)
