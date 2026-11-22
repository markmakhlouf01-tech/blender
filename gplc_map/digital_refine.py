"""Digital restyle of a finished cut, built entirely in Blender's compositor.

Takes the rendered spot and adds a punchier, more digital treatment on top:
beat-synced punch-in zooms and camera shake, RGB channel split, slice and
block glitches, bloom with star streaks on the route nodes, a cool grade,
scanlines, a sweeping scan bar, a faint scrolling tech grid, a live HUD
(corner brackets, timecode, frame counter, coordinate readout), film grain,
a pixel "boot" intro and a CRT power-off outro.

    python digital_refine.py -- SOURCE.mp4 OUT_DIR [PERCENT] [FIRST LAST]
    (or: blender -b --factory-startup -P digital_refine.py -- ...)

Writes OUT_DIR/frames/####.png and OUT_DIR/digital_refine.blend; encode with
render_digital.sh, which also muxes the source audio back in.
"""

import math
import os
import random
import subprocess
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SRC = os.path.abspath(argv[0])
OUT = os.path.abspath(argv[1])
PCT = int(argv[2]) if len(argv) > 2 else 100
FIRST = int(argv[3]) if len(argv) > 4 else None
LAST = int(argv[4]) if len(argv) > 4 else None

W, H = 720, 1280
ACCENT = (0.35, 0.95, 1.0)     # cool cyan, matches the route glow
HOT = (1.0, 0.25, 0.32)        # the red route colour

# --- timing -----------------------------------------------------------------
# (frame, strength 0..1). The first block follows the audio onsets of the
# riser; the rest lands on the film's own beats (route draw-ons, pull-outs,
# globe turns) and a steady 12-frame pulse fills the gaps.
HITS = [
    (14, 0.55),
    (41, 0.3), (45, 0.35), (49, 0.4), (53, 0.45), (57, 0.5), (60, 0.7),
    (63, 1.0), (72, 0.55),
    (96, 0.6), (120, 0.75), (144, 0.6), (168, 0.85), (192, 0.55),
    (216, 0.7), (240, 0.9), (264, 0.55), (288, 0.7), (312, 0.6),
    (336, 0.85), (360, 0.55), (384, 0.75), (408, 0.9), (432, 0.6),
    (450, 0.7),
]
PULSE = 12           # soft zoom bump between hits
INTRO = 16           # pixel boot-up frames
OUTRO = 10           # CRT power-off frames


def env(frame, hits, decay):
    return max((s * math.exp(-(frame - f) / decay) for f, s in hits if frame >= f),
               default=0.0)


# --- scene ------------------------------------------------------------------
sc = bpy.context.scene
for o in list(bpy.data.objects):
    if o.type != "CAMERA":
        bpy.data.objects.remove(o)
clip = bpy.data.movieclips.load(SRC)
clip.colorspace_settings.name = "sRGB"
N = clip.frame_duration
FPS = round(clip.fps)

sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, N
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.resolution_percentage = PCT
sc.render.engine = "CYCLES"           # empty scene, 1 sample: only the compositor matters
sc.cycles.samples = 1
sc.cycles.device = "CPU"
sc.render.compositor_device = "CPU"
sc.render.use_compositing = True
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.render.filepath = os.path.join(OUT, "frames", "")

tree = bpy.data.node_groups.new("DigitalRefine", "CompositorNodeTree")
sc.compositing_node_group = tree
tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
nodes, links = tree.nodes, tree.links
_col = [0]


def node(kind, label=None, **inputs):
    n = nodes.new(kind)
    n.location = (_col[0] * 220, -len(nodes) * 8)
    _col[0] += 1
    if label:
        n.name = n.label = label
    for k, v in inputs.items():
        sock = n.inputs[k]
        if hasattr(v, "bl_idname") or hasattr(v, "is_output"):
            links.new(v, sock)
        else:
            sock.default_value = v
    return n


def out(n, i=0):
    return n.outputs[i]


def link(a, b):
    links.new(a, b)


def math_(op, a, b=None, c=None, clamp=False):
    n = node("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            link(v, n.inputs[i])
    return n.outputs[0]


def vmath(op, a, b=None, scale=None):
    n = node("ShaderNodeVectorMath")
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (tuple, list)):
            n.inputs[i].default_value = v
        else:
            link(v, n.inputs[i])
    if scale is not None:
        if isinstance(scale, (int, float)):
            n.inputs["Scale"].default_value = scale
        else:
            link(scale, n.inputs["Scale"])
    return n.outputs["Value" if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else "Vector"]


def xyz(x, y, z=0.0):
    n = node("ShaderNodeCombineXYZ")
    for i, v in enumerate((x, y, z)):
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            link(v, n.inputs[i])
    return n.outputs[0]


def mix_rgb(blend, a, b, fac):
    n = node("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    n.clamp_result = False
    if isinstance(fac, (int, float)):
        n.inputs[0].default_value = fac
    else:
        link(fac, n.inputs[0])
    for idx, v in ((6, a), (7, b)):
        if isinstance(v, (tuple, list)):
            n.inputs[idx].default_value = (*v, 1.0) if len(v) == 3 else v
        else:
            link(v, n.inputs[idx])
    return n.outputs[2]


# Animated controls: one Value node per parameter, keyed every frame.
CTRL = {}


def control(name):
    n = node("ShaderNodeValue", name)
    CTRL[name] = n
    return n.outputs[0]


zoom = control("zoom")
shake_x = control("shake_x")
shake_y = control("shake_y")
glitch = control("glitch")
split = control("split")
flash = control("flash")
pixel = control("pixel")
crt_y = control("crt_y")
crt_x = control("crt_x")
scan_pos = control("scan_pos")
lat = control("lat")
lon = control("lon")

time = node("CompositorNodeSceneTime")
frame = out(time, "Frame")

# --- source -------------------------------------------------------------------
src = node("CompositorNodeMovieClip")
src.clip = clip
fit = node("CompositorNodeScale", Image=out(src), Type="Render Size")
fit.inputs["Frame Type"].default_value = "Crop"
img = out(fit)

coords = node("CompositorNodeImageCoordinates", Image=img)
uv0 = out(coords, "Normalized")
px = out(coords, "Pixel")
sep_px = node("ShaderNodeSeparateXYZ", Vector=px)
pxx, pxy = out(sep_px, "X"), out(sep_px, "Y")
sep_uv = node("ShaderNodeSeparateXYZ", Vector=uv0)
u0, v0 = out(sep_uv, "X"), out(sep_uv, "Y")

# Zoom about the centre + shake (shake given in UV units).
centred = vmath("SUBTRACT", uv0, (0.5, 0.5, 0.0))
inv_zoom = math_("DIVIDE", 1.0, zoom)
uv = vmath("ADD", vmath("SCALE", centred, scale=inv_zoom), (0.5, 0.5, 0.0))
uv = vmath("ADD", uv, xyz(shake_x, shake_y))

# CRT power-off: squash vertically, then horizontally, around the centre.
uv = vmath("SUBTRACT", uv, (0.5, 0.5, 0.0))
uv = vmath("DIVIDE", uv, xyz(crt_x, crt_y, 1.0))
uv = vmath("ADD", uv, (0.5, 0.5, 0.0))

# Slice glitch: horizontal bands of random height shifted sideways.
band = math_("FLOOR", math_("MULTIPLY", v0, 46.0))
seed = math_("FLOOR", math_("DIVIDE", frame, 2.0))       # re-roll every 2 frames
wn1 = node("ShaderNodeTexWhiteNoise")
wn1.noise_dimensions = "2D"
link(xyz(band, seed), wn1.inputs["Vector"])
wn2 = node("ShaderNodeTexWhiteNoise")
wn2.noise_dimensions = "2D"
link(xyz(math_("ADD", band, 91.7), seed), wn2.inputs["Vector"])
on = math_("GREATER_THAN", out(wn1, "Value"), math_("SUBTRACT", 1.0, math_("MULTIPLY", glitch, 0.45)))
shift = math_("MULTIPLY", math_("MULTIPLY", math_("SUBTRACT", out(wn2, "Value"), 0.5), 0.18),
              math_("MULTIPLY", on, glitch))
uv = vmath("ADD", uv, xyz(shift, 0.0))

# Block glitch mask: rectangular tiles that flicker on during hits.
bx = math_("FLOOR", math_("DIVIDE", pxx, 72.0))
by = math_("FLOOR", math_("DIVIDE", pxy, 26.0))
wn3 = node("ShaderNodeTexWhiteNoise")
wn3.noise_dimensions = "3D"
link(xyz(bx, by, seed), wn3.inputs["Vector"])
block = math_("GREATER_THAN", out(wn3, "Value"), math_("SUBTRACT", 1.0, math_("MULTIPLY", glitch, 0.22)))
uv = vmath("ADD", uv, xyz(math_("MULTIPLY", block, 0.035), math_("MULTIPLY", block, -0.01)))

# RGB split: red and blue sampled at opposite offsets that grow towards the
# edges, plus the per-hit kick from `split`.
radial = vmath("LENGTH", centred)
ca = math_("ADD", math_("MULTIPLY", radial, 0.006), split)
ca_vec = xyz(ca, math_("MULTIPLY", ca, 0.25))


def sample(uv_sock):
    # Map UV reads the vector's Z as coverage (like a UV pass), so force it to 1.
    s = node("ShaderNodeSeparateXYZ", Vector=uv_sock)
    m = node("CompositorNodeMapUV", Image=img, UV=xyz(out(s, "X"), out(s, "Y"), 1.0))
    m.inputs["Interpolation"].default_value = "Bilinear"
    return out(m)


r_img = sample(vmath("ADD", uv, ca_vec))
g_img = sample(uv)
b_img = sample(vmath("SUBTRACT", uv, ca_vec))
comb = node("CompositorNodeCombineColor",
            Red=out(node("CompositorNodeSeparateColor", Image=r_img), "Red"),
            Green=out(node("CompositorNodeSeparateColor", Image=g_img), "Green"),
            Blue=out(node("CompositorNodeSeparateColor", Image=b_img), "Blue"))
im = out(comb)

# Outside the squashed CRT area is black.
cu = node("ShaderNodeSeparateXYZ", Vector=uv)
inside = math_("MULTIPLY",
               math_("MULTIPLY", math_("GREATER_THAN", out(cu, "X"), 0.0), math_("LESS_THAN", out(cu, "X"), 1.0)),
               math_("MULTIPLY", math_("GREATER_THAN", out(cu, "Y"), 0.0), math_("LESS_THAN", out(cu, "Y"), 1.0)))
im = mix_rgb("MIX", (0, 0, 0), im, inside)

# Glitched blocks get pixelated, posterised and tinted.
pix = node("CompositorNodePixelate", Color=im)
pix.inputs["Size"].default_value = 10
post = node("CompositorNodePosterize", Image=out(pix))
post.inputs["Steps"].default_value = 6
tint = mix_rgb("SCREEN", out(post), ACCENT, 0.35)
im = mix_rgb("MIX", im, tint, math_("MULTIPLY", block, 0.85))

# Intro boot: heavy pixelation that resolves.
boot = node("CompositorNodePixelate", Color=im)
link(math_("MAXIMUM", pixel, 1.0), boot.inputs["Size"])
im = mix_rgb("MIX", im, out(boot), math_("GREATER_THAN", pixel, 1.01))

# --- light ------------------------------------------------------------------
grade = node("CompositorNodeColorBalance", Image=im)
grade.inputs["Type"].default_value = "Offset/Power/Slope (ASC-CDL)"
for sock, colour in zip([s for s in grade.inputs if s.type == "RGBA"][1:][-3:],
                        ((0.0, 0.004, 0.018, 1.0),    # offset: cool blacks
                         (1.2, 1.13, 1.06, 1.0),      # power: deeper shadows
                         (1.08, 1.14, 1.2, 1.0))):    # slope: brighter, cooler mids
    sock.default_value = colour
im = out(grade)
hs = node("CompositorNodeHueSat", Image=im)
hs.inputs["Saturation"].default_value = 1.25
hs.inputs["Value"].default_value = 1.0
im = out(hs)

bloom = node("CompositorNodeGlare", Image=im)
bloom.inputs["Type"].default_value = "Bloom"
bloom.inputs["Quality"].default_value = "High"
bloom.inputs["Threshold"].default_value = 0.55
bloom.inputs["Strength"].default_value = 0.85
bloom.inputs["Size"].default_value = 0.6
im = out(bloom)

streaks = node("CompositorNodeGlare", Image=im)
streaks.inputs["Type"].default_value = "Streaks"
streaks.inputs["Quality"].default_value = "High"
streaks.inputs["Threshold"].default_value = 0.92
streaks.inputs["Strength"].default_value = 0.6
streaks.inputs["Streaks"].default_value = 4
streaks.inputs["Streaks Angle"].default_value = math.radians(45)
streaks.inputs["Fade"].default_value = 0.88
im = out(streaks)

# --- digital texture ---------------------------------------------------------
# Scanlines (every 3 px) multiplied in.
sl = math_("MULTIPLY", math_("SINE", math_("MULTIPLY", pxy, 2 * math.pi / 3.0)), 0.5)
sl = math_("ADD", math_("MULTIPLY", sl, 0.16), 0.92)
im = mix_rgb("MULTIPLY", im, xyz(sl, sl, sl), 1.0)

# Scrolling tech grid, stronger towards the frame edges.
gy = math_("ADD", pxy, math_("MULTIPLY", frame, 0.6))
gridx = math_("LESS_THAN", math_("FLOORED_MODULO", pxx, 48.0), 1.0)
gridy = math_("LESS_THAN", math_("FLOORED_MODULO", gy, 48.0), 1.0)
grid = math_("MAXIMUM", gridx, gridy)
dot = math_("MULTIPLY", math_("LESS_THAN", math_("FLOORED_MODULO", pxx, 12.0), 1.0),
            math_("LESS_THAN", math_("FLOORED_MODULO", gy, 12.0), 1.0))
edge = math_("POWER", math_("MULTIPLY", radial, 1.6), 2.0, clamp=False)
grid_a = math_("MULTIPLY", math_("ADD", math_("MULTIPLY", grid, 0.09), math_("MULTIPLY", dot, 0.05)),
               math_("ADD", 0.12, edge))
im = mix_rgb("ADD", im, ACCENT, grid_a)

# Scan bar sweeping top -> bottom with a trailing glow.
d = math_("SUBTRACT", scan_pos, v0)
trail = math_("MULTIPLY", math_("EXPONENT", math_("MULTIPLY", math_("MAXIMUM", d, 0.0), -9.0)),
              math_("GREATER_THAN", d, -0.002))
line = math_("EXPONENT", math_("MULTIPLY", math_("ABSOLUTE", d), -900.0))
im = mix_rgb("ADD", im, ACCENT, math_("ADD", math_("MULTIPLY", trail, 0.06), math_("MULTIPLY", line, 0.55)))

# Vignette.
vig = math_("SUBTRACT", 1.0, math_("MULTIPLY", math_("POWER", radial, 2.2), 1.15), clamp=True)
im = mix_rgb("MULTIPLY", im, xyz(vig, vig, vig), 1.0)

# Grain.
gn = node("ShaderNodeTexWhiteNoise")
gn.noise_dimensions = "3D"
link(xyz(pxx, pxy, frame), gn.inputs["Vector"])
grain = math_("MULTIPLY", math_("SUBTRACT", out(gn, "Value"), 0.5), 0.045)
im = mix_rgb("ADD", im, xyz(grain, grain, grain), 1.0)

# --- HUD --------------------------------------------------------------------
font = None
for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"):
    if os.path.exists(path):
        font = bpy.data.fonts.load(path)
        break

hud_mask_parts = []


def box(cx, cy, w, h):
    """Box in pixels, centre-based, returned as a 0/1 mask."""
    m = node("CompositorNodeBoxMask")
    m.inputs["Position"].default_value = (cx / W, cy / H)
    m.inputs["Size"].default_value = (w / W, h / H)
    return out(m)


M, L, T = 34, 64, 3   # margin, bracket arm length, thickness
for sx in (-1, 1):
    for sy in (-1, 1):
        cx = W / 2 + sx * (W / 2 - M)
        cy = H / 2 + sy * (H / 2 - M)
        hud_mask_parts.append(box(cx - sx * L / 2, cy, L, T))
        hud_mask_parts.append(box(cx, cy - sy * L / 2, T, L))
# Centre reticle.
hud_mask_parts += [box(W / 2 - 22, H / 2, 16, 2), box(W / 2 + 22, H / 2, 16, 2),
                   box(W / 2, H / 2 - 22, 2, 16), box(W / 2, H / 2 + 22, 2, 16)]
# Ticks along the right edge.
for i in range(-12, 13):
    hud_mask_parts.append(box(W - M + 8, H / 2 + i * 22, 10 if i % 4 else 18, 2))

hud = hud_mask_parts[0]
for m in hud_mask_parts[1:]:
    hud = math_("MAXIMUM", hud, m)


def text(string_sock, size, x, y, align="Left"):
    t = node("CompositorNodeStringToImage")
    if isinstance(string_sock, str):
        t.inputs["String"].default_value = string_sock
    else:
        link(string_sock, t.inputs["String"])
    if font:
        t.inputs["Font"].default_value = font
    t.inputs["Size"].default_value = size
    t.inputs["Horizontal Alignment"].default_value = align
    tr = node("CompositorNodeTranslate", Image=out(t))
    tr.inputs["X"].default_value = x
    tr.inputs["Y"].default_value = y
    return out(tr)


def num(value_sock, decimals=0, pad=0):
    n = node("FunctionNodeValueToString", Value=value_sock)
    n.inputs["Decimals"].default_value = decimals
    if "Padding" in n.inputs:
        n.inputs["Padding"].default_value = pad
    return out(n)


seconds = out(time, "Seconds")
X0, X1 = -W / 2 + M + 14, W / 2 - M - 14
labels = [
    text("GLOBAL TRADE NETWORK", 17, X0, H / 2 - M - 30),
    text("// LIVE", 17, X0 + 222, H / 2 - M - 30),
    text("T+", 17, X0, H / 2 - M - 56),
    text(num(seconds, 2, 5), 17, X0 + 26, H / 2 - M - 56),
    text("FRM", 15, X1 - 108, H / 2 - M - 30),
    text(num(frame, 0, 4), 15, X1 - 64, H / 2 - M - 30),
    text("LAT", 15, X0, -H / 2 + M + 52),
    text(num(lat, 3), 15, X0 + 44, -H / 2 + M + 52),
    text("LON", 15, X0, -H / 2 + M + 28),
    text(num(lon, 3), 15, X0 + 44, -H / 2 + M + 28),
    text("NODES ONLINE", 15, X1 - 172, -H / 2 + M + 28),
]

# Blinking REC-style dot in the HUD colour.
blink = math_("GREATER_THAN", math_("FLOORED_MODULO", frame, 24.0), 11.0)
dot_m = node("CompositorNodeEllipseMask")
dot_m.inputs["Position"].default_value = ((W / 2 + X0 + 316) / W, (H - M - 24) / H)
dot_m.inputs["Size"].default_value = (12 / W, 12 / H)
hud = math_("MAXIMUM", hud, math_("MULTIPLY", out(dot_m), blink))

# HUD flickers with the glitch and dims during the intro / outro.
hud_alpha = math_("MULTIPLY", math_("SUBTRACT", 1.0, math_("MULTIPLY", glitch, 0.5)), 0.85)
hud_alpha = math_("MULTIPLY", hud_alpha, math_("SUBTRACT", 1.0, math_("DIVIDE", math_("MINIMUM", pixel, 40.0), 40.0)))
hud_alpha = math_("MULTIPLY", hud_alpha, inside)
im = mix_rgb("MIX", im, ACCENT, math_("MULTIPLY", hud, hud_alpha))
for lab in labels:
    sep = node("CompositorNodeSeparateColor", Image=lab)
    # The text box is opaque; the glyphs are in the colour channels.
    a = math_("MULTIPLY", math_("MULTIPLY", out(sep, "Red"), out(sep, "Alpha")), hud_alpha)
    im = mix_rgb("MIX", im, (0.86, 0.98, 1.0, 1.0), a)

# Flash on the biggest hits.
im = mix_rgb("ADD", im, (0.55, 0.9, 1.0), flash)

link(im, nodes.new("NodeGroupOutput").inputs[0])

# --- animation ---------------------------------------------------------------
rng = random.Random(7)
noise_x = [rng.uniform(-1, 1) for _ in range(N + 2)]
noise_y = [rng.uniform(-1, 1) for _ in range(N + 2)]
pulses = [(f, 0.35) for f in range(PULSE * 2, N, PULSE)]

for f in range(1, N + 1):
    hit = env(f, HITS, 5.0)
    hit_fast = env(f, HITS, 2.2)
    bump = env(f, pulses, 4.0)
    # Slow push that resets on each big hit, so the frame never sits still.
    last_big = max((h for h, s in HITS if h <= f and s >= 0.7), default=1)
    push = 0.06 + 0.0012 * (f - last_big)
    vals = {
        "zoom": 1.0 + min(push, 0.12) + 0.11 * hit + 0.018 * bump,
        "shake_x": (0.0015 + 0.012 * hit_fast) * noise_x[f],
        "shake_y": (0.0010 + 0.007 * hit_fast) * noise_y[f],
        "glitch": min(1.0, 1.3 * env(f, [(h, s) for h, s in HITS if s >= 0.5], 2.0)),
        "split": 0.0015 + 0.014 * hit_fast,
        "flash": 0.3 * env(f, [(h, s) for h, s in HITS if s >= 0.85], 1.4),
        "pixel": 1.0,
        "crt_y": 1.0,
        "crt_x": 1.0,
        "scan_pos": 1.15 - ((f % 60) / 60.0) * 1.3,
        "lat": 24.713 - 0.0021 * f + 0.004 * math.sin(f * 0.21),
        "lon": 46.675 + 0.0047 * f + 0.004 * math.cos(f * 0.17),
    }
    if f <= INTRO:
        k = (f - 1) / (INTRO - 1)
        vals["pixel"] = 1.0 + 48.0 * (1 - k) ** 2.2
        vals["glitch"] = max(vals["glitch"], 1.0 - k)
        vals["split"] += 0.02 * (1 - k)
    if f > N - OUTRO:
        k = (f - (N - OUTRO)) / OUTRO              # 0 -> 1
        vals["crt_y"] = max(0.004, 1.0 - min(1.0, k * 1.6))
        vals["crt_x"] = 1.0 if k < 0.62 else max(0.002, 1.0 - (k - 0.62) / 0.38)
        vals["flash"] = max(vals["flash"], 0.6 * k)
        vals["glitch"] = max(vals["glitch"], 0.7)
    for name, v in vals.items():
        sock = CTRL[name].outputs[0]
        sock.default_value = v
        sock.keyframe_insert("default_value", frame=f)

if tree.animation_data and tree.animation_data.action:
    act = tree.animation_data.action
    curves = act.fcurves if hasattr(act, "fcurves") else [
        c for layer in act.layers for strip in layer.strips
        for bag in strip.channelbags for c in bag.fcurves]
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"

os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "digital_refine.blend"))

if FIRST is not None:
    sc.frame_start, sc.frame_end = FIRST, LAST
bpy.ops.render.render(animation=True)
