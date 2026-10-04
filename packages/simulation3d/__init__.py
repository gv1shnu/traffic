"""World-space traffic simulation for rendered 3D evaluation scenes.

The microsimulation here produces vehicle and pedestrian trajectories in metres
with known ground truth. A separate Blender script (scripts/sim3d/) turns those
trajectories into rendered video, which is then analysed by the real detection,
tracking and attribution pipeline. Nothing in this package is imported by the
production investigation pipeline.
"""
