"""Refine a video in Blender's compositor: denoise, upscale, sharpen, bloom, grade.

    blender -b --factory-startup -P refine.py -- IN.mp4 OUT.mp4 [--size 1080x1920] [--frames a-b]
    python refine.py IN.mp4 OUT.mp4 ...        # same, with the `bpy` module

The source audio is carried over through a VSE sound strip.
"""
import argparse
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--size", default="1080x1920", help="output WxH (default: 9:16 full HD)")
ap.add_argument("--frames", help="render only this range, e.g. 1-48")
ap.add_argument("--still", type=int, help="render a single frame to DST as PNG")
ap.add_argument("--save-blend", help="also save the set-up scene here")
args = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.data.scenes[0]
clip = bpy.data.movieclips.load(args.src)
src_w, src_h = clip.size
fps = round(clip.fps) or 24

r = scene.render
r.resolution_x, r.resolution_y = (int(v) for v in args.size.split("x"))
r.resolution_percentage = 100
r.fps = fps
scene.frame_start = 1
scene.frame_end = clip.frame_duration
if args.frames:
    a, b = (int(x) for x in args.frames.split("-"))
    scene.frame_start, scene.frame_end = a, b
# Keep the source's look: no filmic/AgX tone mapping on top of display-referred footage.
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
# The 3D scene is empty; a 1-sample CPU Cycles pass keeps headless renders GPU-free.
r.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
r.compositor_device = "CPU"
r.use_compositing = True

tree = bpy.data.node_groups.new("Refine", "CompositorNodeTree")
tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
scene.compositing_node_group = tree
N, L = tree.nodes, tree.links
x = 0


def node(kind, **inputs):
    global x
    n = N.new(kind)
    n.location = (x, 0)
    x += 220
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def mix(blend, a, b, fac):
    m = node("ShaderNodeMix")
    m.data_type = "RGBA"
    m.blend_type = blend
    m.inputs[0].default_value = fac
    L.new(a, m.inputs[6])
    L.new(b, m.inputs[7])
    return m.outputs[2]


src = node("CompositorNodeMovieClip")
src.clip = clip

# 1. Clean compression noise/blocking at source size, keep some original texture.
den = node("CompositorNodeDenoise", Prefilter="None", HDR=False)
L.new(src.outputs["Image"], den.inputs["Image"])
img = mix("MIX", src.outputs["Image"], den.outputs["Image"], 0.55)

# 2. Upscale to render size.
up = node("CompositorNodeScale", Type="Render Size", Interpolation="Bicubic")
up.inputs["Frame Type"].default_value = "Stretch"
L.new(img, up.inputs["Image"])

# 3. Restore edge definition lost to the upscale.
sh = node("CompositorNodeFilter", Type="Diamond Sharpen", Factor=0.22)
L.new(up.outputs["Image"], sh.inputs["Image"])

# 4. Gentle grade: deeper blacks, a touch more contrast and saturation.
cb = node("CompositorNodeColorBalance", Type="Offset/Power/Slope (ASC-CDL)")
cb.inputs[11].default_value = 1.0                          # Offset
cb.inputs[12].default_value = (0.985, 0.99, 1.0, 1.0)      # Offset colour (cool shadows)
cb.inputs[13].default_value = 1.12                         # Power
cb.inputs[15].default_value = 1.06                         # Slope
L.new(sh.outputs["Image"], cb.inputs["Image"])
hs = node("CompositorNodeHueSat", Saturation=1.12, Value=1.0)
L.new(cb.outputs["Image"], hs.inputs["Image"])

# 5. Bloom on the glowing routes, city dots and atmosphere rim.
gl = node("CompositorNodeGlare", Type="Bloom", Quality="High", Threshold=0.55,
          Smoothness=0.4, Strength=0.45, Saturation=1.15, Size=0.6)
L.new(hs.outputs["Image"], gl.inputs["Image"])

# 6. Soft vignette to hold the eye on the globe.
ell = node("CompositorNodeEllipseMask", Size=(1.15, 1.05))
ell.inputs["Operation"].default_value = "Add"
bl = node("CompositorNodeBlur", Size=(r.resolution_x * 0.18, r.resolution_y * 0.18))
bl.inputs["Type"].default_value = "Gaussian"
ell_img = ell.outputs["Mask"]
L.new(ell_img, bl.inputs["Image"])
vig = node("ShaderNodeMix")
vig.data_type = "RGBA"
vig.blend_type = "MULTIPLY"
vig.inputs[0].default_value = 1.0
L.new(gl.outputs["Image"], vig.inputs[6])
# mask 0 -> 0.72, mask 1 -> 1.0
mr = node("ShaderNodeMapRange")
mr.inputs["To Min"].default_value = 0.72
L.new(bl.outputs["Image"], mr.inputs["Value"])
L.new(mr.outputs["Result"], vig.inputs[7])

out = node("NodeGroupOutput")
L.new(vig.outputs[2], out.inputs[0])

# Audio rides along in the sequencer (sound-only strips don't override the compositor).
if args.still is None:
    seq = scene.sequence_editor_create()
    strips = seq.strips if hasattr(seq, "strips") else seq.sequences
    try:
        strips.new_sound("audio", args.src, 1, 1)
    except Exception as e:  # silent source
        print("no audio:", e)

if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)

if args.still is not None:
    scene.frame_set(args.still)
    r.image_settings.file_format = "PNG"
    r.filepath = args.dst
    bpy.ops.render.render(write_still=True)
else:
    if hasattr(r.image_settings, "media_type"):  # Blender 5.0+
        r.image_settings.media_type = "VIDEO"
    r.image_settings.file_format = "FFMPEG"
    ff = r.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    ff.constant_rate_factor = "HIGH"
    ff.ffmpeg_preset = "GOOD"
    ff.gopsize = fps
    ff.audio_codec = "AAC"
    ff.audio_bitrate = 192
    ff.audio_mixrate = 48000
    ff.audio_channels = "STEREO"
    r.use_file_extension = False
    r.filepath = args.dst
    bpy.ops.render.render(animation=True)
