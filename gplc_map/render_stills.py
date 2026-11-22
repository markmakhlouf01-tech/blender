"""Render selected frames of a scene for review.
blender -b file.blend -P render_stills.py -- <scene> <out_dir> f1 f2 ..."""
import os
import sys
import time

import bpy

a = sys.argv[sys.argv.index("--") + 1:]
scene = bpy.data.scenes[a[0]]
out = a[1]
os.makedirs(out, exist_ok=True)
bpy.context.window.scene = scene if bpy.context.window else None
for f in map(int, a[2:]):
    scene.frame_set(f)
    scene.render.filepath = os.path.join(out, f"{a[0]}_{f:04d}.png")
    t = time.time()
    bpy.ops.render.render(write_still=True, scene=scene.name)
    print(f"STILL {a[0]} {f} {time.time() - t:.1f}s", flush=True)
