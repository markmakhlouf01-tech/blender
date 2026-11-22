"""Build (and optionally render) the globe-routes film.

    blender -b --factory-startup -P build_globe.py -- DATA_DIR OUT [options]
    python build_globe.py DATA_DIR OUT [options]          # with the `bpy` wheel

DATA_DIR holds earth_color.png and earth_color_4k.png (prep/build_earth.py).
OUT is the .mp4 to write, a directory ending in / for a PNG sequence,
or with --still N[,M...] a PNG path (#### = frame number).
Options: --pct 50 (resolution %), --samples 16, --frames a-b, --save-blend FILE, --no-render.

Everything is emission-shaded (globe, atmosphere, routes, stars), so frames are
noise-free and stable from one frame to the next. Line and node sizes follow the
camera distance so they stay the same on-screen width at every zoom.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routes import CAMERA, CITIES, FPS, FRAMES, HUBS, ROUTES  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("out")
ap.add_argument("--pct", type=int, default=100)
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--frames")
ap.add_argument("--still", help="frame number(s), comma-separated; OUT is a PNG path or pattern with ####")
ap.add_argument("--save-blend")
ap.add_argument("--no-render", action="store_true")
args = ap.parse_args(argv)

R_LINE = 1.002        # route / node altitude (globe radius = 1)
LINE_PX = {"land": 0.00095, "sea": 0.00075}   # tube radius per unit camera distance
DOT_K, HUB_K = 0.0034, 0.0044
WHITE = (1.0, 1.0, 1.0, 1.0)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.data.scenes[0]
scene.name = "Globe"


def xyz(lon, lat, r=1.0):
    lo, la = math.radians(lon), math.radians(lat)
    return Vector((math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))) * r


def node(nt, kind, **inputs):
    n = nt.nodes.new(kind)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def math_node(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def ease_keys(fcurves, interp="SINE", easing="EASE_IN_OUT"):
    for fc in fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            kp.easing = easing


# ---------------------------------------------------------------- camera rig
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 35
cam_data.sensor_fit = "VERTICAL"
cam_data.sensor_height = 36
cam_data.clip_start = 0.005
cam_data.clip_end = 100
cam = bpy.data.objects.new("Camera", cam_data)
orbit = bpy.data.objects.new("CamOrbit", None)
heading = bpy.data.objects.new("CamHeading", None)
target = bpy.data.objects.new("CamTarget", None)
for ob in (orbit, heading, target, cam):
    scene.collection.objects.link(ob)
heading.parent = orbit
target.parent = heading
cam.parent = heading
target.location = (1, 0, 0)
scene.camera = cam
tc = cam.constraints.new("TRACK_TO")
tc.target = target
tc.track_axis = "TRACK_NEGATIVE_Z"
tc.up_axis = "UP_Y"
tc.use_target_z = True

for f, lon, lat, h, tilt, hd in CAMERA:
    orbit.rotation_euler = (0, -math.radians(lat), math.radians(lon))
    orbit.keyframe_insert("rotation_euler", frame=f)
    heading.rotation_euler = (math.radians(hd), 0, 0)
    heading.keyframe_insert("rotation_euler", frame=f)
    t = math.radians(tilt)
    cam.location = (1 + h * math.cos(t), 0, -h * math.sin(t))
    cam.keyframe_insert("location", frame=f)

def iter_fcurves(id_data):
    act = id_data.animation_data.action
    if hasattr(act, "fcurves"):
        yield from act.fcurves
        return
    for layer in act.layers:  # Blender 5 layered actions
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


for ob in (orbit, heading, cam):
    for fc in iter_fcurves(ob):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()


def dist_driver(owner, path, k, index=-1):
    """owner.path = k * |camera - look-at point| (keeps a constant on-screen size)."""
    fcs = owner.driver_add(path, index)
    for fc in fcs if isinstance(fcs, list) else [fcs]:
        d = fc.driver
        d.type = "SCRIPTED"
        v = d.variables.new()
        v.name = "d"
        v.type = "LOC_DIFF"
        v.targets[0].id = cam
        v.targets[1].id = target
        d.expression = f"{k} * d"


# ---------------------------------------------------------------- globe
def load(name):
    img = bpy.data.images.load(os.path.join(args.data, name))
    img.colorspace_settings.name = "sRGB"
    return img


bpy.ops.mesh.primitive_uv_sphere_add(segments=512, ring_count=256, radius=1.0)
globe = bpy.context.active_object
globe.name = "Globe"
bpy.ops.object.shade_smooth()
mat = bpy.data.materials.new("Earth")
nt = mat.node_tree
nt.nodes.clear()
tco = nt.nodes.new("ShaderNodeTexCoord")
nrm = nt.nodes.new("ShaderNodeVectorMath")
nrm.operation = "NORMALIZE"
nt.links.new(tco.outputs["Object"], nrm.inputs[0])
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(nrm.outputs[0], sep.inputs[0])
u = math_node(nt, "ADD", math_node(nt, "DIVIDE", math_node(nt, "ARCTAN2", sep.outputs["Y"], sep.outputs["X"]),
                                    2 * math.pi), 0.5)
v = math_node(nt, "ADD", math_node(nt, "DIVIDE", math_node(nt, "ARCSINE", sep.outputs["Z"]), math.pi), 0.5)
uv = nt.nodes.new("ShaderNodeCombineXYZ")
nt.links.new(u, uv.inputs["X"])
nt.links.new(v, uv.inputs["Y"])
tex_hi = nt.nodes.new("ShaderNodeTexImage")
tex_hi.image = load("earth_color.png")
tex_lo = nt.nodes.new("ShaderNodeTexImage")
tex_lo.image = load("earth_color_4k.png")
for t in (tex_hi, tex_lo):
    t.interpolation = "Cubic"
    t.extension = "REPEAT"
    nt.links.new(uv.outputs[0], t.inputs["Vector"])
# Near: 16k map. Far: the 4k map, pre-filtered, so the globe does not shimmer when small.
lod = nt.nodes.new("ShaderNodeValue")
lod.name = "LOD"
mix = nt.nodes.new("ShaderNodeMix")
mix.data_type = "RGBA"
nt.links.new(lod.outputs[0], mix.inputs[0])
nt.links.new(tex_hi.outputs["Color"], mix.inputs[6])
nt.links.new(tex_lo.outputs["Color"], mix.inputs[7])
fcl = lod.outputs[0].driver_add("default_value")
fcl.driver.type = "SCRIPTED"
var = fcl.driver.variables.new()
var.name, var.type = "d", "LOC_DIFF"
var.targets[0].id, var.targets[1].id = cam, target
fcl.driver.expression = "min(max((d - 0.9) / 0.7, 0.0), 1.0)"
# View-facing shading: bright centre, darker limb (no light sources -> no noise).
geo = nt.nodes.new("ShaderNodeNewGeometry")
dot = nt.nodes.new("ShaderNodeVectorMath")
dot.operation = "DOT_PRODUCT"
nt.links.new(geo.outputs["Normal"], dot.inputs[0])
nt.links.new(geo.outputs["Incoming"], dot.inputs[1])
facing = math_node(nt, "MAXIMUM", dot.outputs["Value"], 0.0)
shade = math_node(nt, "ADD", math_node(nt, "MULTIPLY", math_node(nt, "POWER", facing, 0.8), 0.9), 0.22)
cmul = nt.nodes.new("ShaderNodeMix")
cmul.data_type = "RGBA"
cmul.blend_type = "MULTIPLY"
cmul.inputs[0].default_value = 1.0
nt.links.new(mix.outputs[2], cmul.inputs[6])
shade_rgb = nt.nodes.new("ShaderNodeCombineColor")
for s in ("Red", "Green", "Blue"):
    nt.links.new(shade, shade_rgb.inputs[s])
nt.links.new(shade_rgb.outputs[0], cmul.inputs[7])
em = node(nt, "ShaderNodeEmission", Strength=1.0)
nt.links.new(cmul.outputs[2], em.inputs["Color"])
mo = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(em.outputs[0], mo.inputs["Surface"])
globe.data.materials.append(mat)

# Atmosphere: additive rim glow on a slightly larger shell.
bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, radius=1.022)
atm = bpy.context.active_object
atm.name = "Atmosphere"
bpy.ops.object.shade_smooth()
am = bpy.data.materials.new("Atmosphere")
an = am.node_tree
an.nodes.clear()
lw = node(an, "ShaderNodeLayerWeight", Blend=0.5)
rim = math_node(an, "POWER", lw.outputs["Facing"], 3.2)
glow = node(an, "ShaderNodeEmission", Color=(0.22, 0.55, 1.0, 1.0))
front = math_node(an, "SUBTRACT", 1.0, an.nodes.new("ShaderNodeNewGeometry").outputs["Backfacing"])
an.links.new(math_node(an, "MULTIPLY", math_node(an, "MULTIPLY", rim, 0.85), front), glow.inputs["Strength"])
add = an.nodes.new("ShaderNodeAddShader")
an.links.new(node(an, "ShaderNodeBsdfTransparent").outputs[0], add.inputs[0])
an.links.new(glow.outputs[0], add.inputs[1])
an.links.new(add.outputs[0], node(an, "ShaderNodeOutputMaterial").inputs["Surface"])
atm.data.materials.append(am)
atm.visible_shadow = False

# Stars: sparse, round, ~2 px, fixed brightness (no twinkle).
world = bpy.data.worlds.new("Space")
scene.world = world
wn = world.node_tree
wn.nodes.clear()
wt = wn.nodes.new("ShaderNodeTexCoord")
vor = node(wn, "ShaderNodeTexVoronoi", Scale=150.0)
vor.voronoi_dimensions = "3D"
wn.links.new(wt.outputs["Generated"], vor.inputs["Vector"])
sepc = wn.nodes.new("ShaderNodeSeparateColor")
wn.links.new(vor.outputs["Color"], sepc.inputs[0])
keep = math_node(wn, "GREATER_THAN", sepc.outputs["Red"], 0.94)
core = wn.nodes.new("ShaderNodeMapRange")
core.interpolation_type = "SMOOTHSTEP"
core.inputs["From Min"].default_value = 0.11
core.inputs["From Max"].default_value = 0.03
wn.links.new(vor.outputs["Distance"], core.inputs["Value"])
bright = math_node(wn, "ADD", math_node(wn, "MULTIPLY", sepc.outputs["Green"], 0.7), 0.15)
star = math_node(wn, "MULTIPLY", math_node(wn, "MULTIPLY", keep, core.outputs[0]), bright)
bgmix = wn.nodes.new("ShaderNodeMix")
bgmix.data_type = "RGBA"
wn.links.new(star, bgmix.inputs[0])
bgmix.inputs[6].default_value = (0.0035, 0.006, 0.009, 1)
bgmix.inputs[7].default_value = (0.85, 0.9, 1.0, 1)
bg = node(wn, "ShaderNodeBackground", Strength=1.0)
wn.links.new(bgmix.outputs[2], bg.inputs["Color"])
wn.links.new(bg.outputs[0], wn.nodes.new("ShaderNodeOutputWorld").inputs["Surface"])


# ---------------------------------------------------------------- routes
def emission_mat(name, strength):
    m = bpy.data.materials.new(name)
    m.node_tree.nodes.clear()
    e = node(m.node_tree, "ShaderNodeEmission", Color=WHITE, Strength=strength)
    m.node_tree.links.new(e.outputs[0], node(m.node_tree, "ShaderNodeOutputMaterial").inputs["Surface"])
    return m


mat_line = {"land": emission_mat("LineLand", 4.0), "sea": emission_mat("LineSea", 3.0)}
mat_dot = emission_mat("Node", 5.0)


def ll(w):
    return CITIES[w] if isinstance(w, str) else w


def smooth_path(waypoints, step_deg=0.12):
    """Centripetal Catmull-Rom through the waypoints on the sphere, evenly resampled."""
    P = [xyz(*ll(w)) for w in waypoints]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    pts, knots = [], []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t0 = 0.0
        t1 = t0 + max((p1 - p0).length, 1e-6) ** 0.5
        t2 = t1 + max((p2 - p1).length, 1e-6) ** 0.5
        t3 = t2 + max((p3 - p2).length, 1e-6) ** 0.5
        n = max(2, int(math.degrees(p1.angle(p2)) / step_deg))
        knots.append(len(pts))
        for j in range(n):
            t = t1 + (t2 - t1) * j / n
            a1 = p0 * ((t1 - t) / (t1 - t0)) + p1 * ((t - t0) / (t1 - t0))
            a2 = p1 * ((t2 - t) / (t2 - t1)) + p2 * ((t - t1) / (t2 - t1))
            a3 = p2 * ((t3 - t) / (t3 - t2)) + p3 * ((t - t2) / (t3 - t2))
            b1 = a1 * ((t2 - t) / (t2 - t0)) + a2 * ((t - t0) / (t2 - t0))
            b2 = a2 * ((t3 - t) / (t3 - t1)) + a3 * ((t - t1) / (t3 - t1))
            pts.append((b1 * ((t2 - t) / (t2 - t1)) + b2 * ((t - t1) / (t2 - t1))).normalized() * R_LINE)
    knots.append(len(pts))
    pts.append(P[-2].normalized() * R_LINE)
    return pts, knots


def ease_inv(p):
    """Inverse of Blender's SINE ease-in-out: progress -> time fraction."""
    return math.acos(max(-1.0, min(1.0, 1 - 2 * p))) / math.pi


arrival = {}
lines = bpy.data.collections.new("Routes")
scene.collection.children.link(lines)
for name, kind, f0, f1, wps in ROUTES:
    pts, knots = smooth_path(wps)
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    cu.bevel_factor_mapping_end = "SPLINE"
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, co in zip(sp.points, pts):
        p.co = (co.x, co.y, co.z, 1.0)
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(mat_line[kind])
    lines.objects.link(ob)
    dist_driver(cu, "bevel_depth", LINE_PX[kind])
    cu.bevel_factor_end = 0.0
    cu.keyframe_insert("bevel_factor_end", frame=f0)
    cu.bevel_factor_end = 1.0
    cu.keyframe_insert("bevel_factor_end", frame=f1)
    ease_keys(iter_fcurves(cu))
    ob.cycles.use_motion_blur = False
    # When does the line reach each named city on it?
    seg = [(Vector(pts[i + 1]) - Vector(pts[i])).length for i in range(len(pts) - 1)]
    total = sum(seg)
    cum = [0.0]
    for s in seg:
        cum.append(cum[-1] + s)
    for w, k in zip(wps, knots):
        if isinstance(w, str):
            f = f0 + (f1 - f0) * ease_inv(cum[k] / total)
            arrival[w] = min(arrival.get(w, 1e9), f)

# ---------------------------------------------------------------- nodes
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
dot_mesh = bpy.context.active_object.data
bpy.ops.object.shade_smooth()
bpy.data.objects.remove(bpy.context.active_object)
dot_mesh.materials.append(mat_dot)
bpy.ops.mesh.primitive_torus_add(major_radius=2.4, minor_radius=0.16, major_segments=96, minor_segments=12)
ring_mesh = bpy.context.active_object.data
bpy.ops.object.shade_smooth()
bpy.data.objects.remove(bpy.context.active_object)
ring_mesh.materials.append(emission_mat("Ring", 2.2))

nodes = bpy.data.collections.new("Nodes")
scene.collection.children.link(nodes)
for city, f in sorted(arrival.items(), key=lambda kv: kv[1]):
    n = xyz(*CITIES[city])
    pivot = bpy.data.objects.new("City " + city, None)
    pivot.location = n * R_LINE
    pivot.rotation_euler = n.to_track_quat("Z", "Y").to_euler()
    nodes.objects.link(pivot)
    f = round(f)
    pivot.scale = (0, 0, 0)
    pivot.keyframe_insert("scale", frame=f - 1)
    pivot.scale = (1, 1, 1)
    pivot.keyframe_insert("scale", frame=f + 5)
    ease_keys(iter_fcurves(pivot), "CUBIC", "EASE_OUT")
    parts = [("Dot", dot_mesh, HUB_K if city in HUBS else DOT_K)]
    if city in HUBS:
        parts.append(("Ring", ring_mesh, HUB_K))
    for label, mesh, k in parts:
        ob = bpy.data.objects.new(f"{label} {city}", mesh)
        ob.parent = pivot
        nodes.objects.link(ob)
        dist_driver(ob, "scale", k)

# ---------------------------------------------------------------- render
r = scene.render
r.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = args.samples
scene.cycles.use_adaptive_sampling = False
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 4
scene.cycles.diffuse_bounces = scene.cycles.glossy_bounces = 0
scene.cycles.transmission_bounces = scene.cycles.volume_bounces = 0
scene.cycles.transparent_max_bounces = 8
r.filter_size = 1.5
r.use_persistent_data = True
r.use_motion_blur = True
r.motion_blur_shutter = 0.3
r.resolution_x, r.resolution_y = 1080, 1920
r.resolution_percentage = args.pct
r.fps = FPS
scene.frame_start, scene.frame_end = 1, FRAMES
if args.frames:
    scene.frame_start, scene.frame_end = (int(x) for x in args.frames.split("-"))
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
# Fade up from black.
scene.view_settings.exposure = -8
scene.keyframe_insert("view_settings.exposure", frame=1)
scene.view_settings.exposure = 0
scene.keyframe_insert("view_settings.exposure", frame=14)

# Compositor: steady bloom on lines/nodes/atmosphere + soft vignette.
tree = bpy.data.node_groups.new("Finish", "CompositorNodeTree")
tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
scene.compositing_node_group = tree
rl = tree.nodes.new("CompositorNodeRLayers")
rl.scene = scene
gl = node(tree, "CompositorNodeGlare", Type="Bloom", Quality="High", Threshold=0.95,
          Smoothness=0.3, Strength=0.55, Saturation=0.0, Size=0.55)
tree.links.new(rl.outputs["Image"], gl.inputs["Image"])
ell = node(tree, "CompositorNodeEllipseMask", Size=(1.2, 1.05))
ell.inputs["Operation"].default_value = "Add"
blur = node(tree, "CompositorNodeBlur", Size=(200.0, 350.0))
blur.inputs["Type"].default_value = "Gaussian"
tree.links.new(ell.outputs["Mask"], blur.inputs["Image"])
mr = tree.nodes.new("ShaderNodeMapRange")
mr.inputs["To Min"].default_value = 0.7
tree.links.new(blur.outputs["Image"], mr.inputs["Value"])
vig = tree.nodes.new("ShaderNodeMix")
vig.data_type = "RGBA"
vig.blend_type = "MULTIPLY"
vig.inputs[0].default_value = 1.0
tree.links.new(gl.outputs["Image"], vig.inputs[6])
tree.links.new(mr.outputs["Result"], vig.inputs[7])
tree.links.new(vig.outputs[2], tree.nodes.new("NodeGroupOutput").inputs[0])
r.compositor_device = "CPU"
r.use_compositing = True

if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))
if args.no_render:
    sys.exit(0)
if args.still is not None:
    r.image_settings.file_format = "PNG"
    for f in (int(x) for x in args.still.split(",")):
        scene.frame_set(f)
        r.filepath = args.out.replace("####", f"{f:04d}")
        bpy.ops.render.render(write_still=True)
elif args.out.endswith("/"):  # PNG sequence (resumable: existing frames are skipped)
    r.image_settings.file_format = "PNG"
    r.use_overwrite = False
    r.use_placeholder = True
    r.filepath = args.out
    bpy.ops.render.render(animation=True)
else:
    if hasattr(r.image_settings, "media_type"):
        r.image_settings.media_type = "VIDEO"
    r.image_settings.file_format = "FFMPEG"
    ff = r.ffmpeg
    ff.format, ff.codec = "MPEG4", "H264"
    ff.constant_rate_factor = "HIGH"
    ff.ffmpeg_preset = "GOOD"
    ff.gopsize = FPS
    r.use_file_extension = False
    r.filepath = args.out
    bpy.ops.render.render(animation=True)
