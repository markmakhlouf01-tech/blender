"""GPLC 'On the map' - Blender scene builder.

Run:
  blender -b --factory-startup -P build_scene.py -- <data_dir> <out_dir> [res_percent]

Builds three scenes in one .blend:
  Map   - displaced relief map, night lights, white animated route lines, ship
  UI    - orthographic 2D overlay: logo, titles, progress bar, wipe, end card
  Edit  - VSE timeline that stacks the rendered Map + UI frames into an MP4
"""
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from config import (LON0, LON1, LAT0, LAT1, DEG_PER_PX, FPS, RES_X, RES_Y,  # noqa: E402
                    project)
from timeline import T  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DATA = os.path.abspath(argv[0])
OUT = os.path.abspath(argv[1])
RES_PCT = int(argv[2]) if len(argv) > 2 else 50
TEX = os.path.join(DATA, "tex")
LOGOS = os.path.join(DATA, "logos")
FONTS = os.path.join(DATA, "fonts")
os.makedirs(OUT, exist_ok=True)

COLORS = json.load(open(os.path.join(LOGOS, "colors.json")))
LINES = json.load(open(os.path.join(DATA, "lines.json")))


def srgb_to_lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


INK = srgb_to_lin(COLORS["ink"])
GOLD = srgb_to_lin(COLORS["gold"])
GREEN = srgb_to_lin(COLORS["green"])
BG = (0.0035, 0.0055, 0.011)

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def smooth_keys(id_data, ease="AUTO_CLAMPED"):
    ad = id_data.animation_data
    if not ad or not ad.action:
        return
    for fc in iter_fcurves(ad.action):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = ease
            kp.handle_right_type = ease
        fc.update()


def iter_fcurves(action):
    # Blender 4.4+ layered actions; fall back to legacy fcurves.
    if hasattr(action, "layers") and len(action.layers):
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    yield from cb.fcurves
    elif hasattr(action, "fcurves"):
        yield from action.fcurves


def keys(target, path, frames_values, index=-1):
    """Keyframe target.path at several (frame, value) pairs."""
    for f, v in frames_values:
        if index >= 0:
            arr = getattr(target, path)
            arr[index] = v
        elif path.startswith("["):
            target[path[2:-2]] = v
        else:
            setattr(target, path, v)
        target.keyframe_insert(path, frame=f, index=index)


def node(nt, typ, loc=(0, 0), **kw):
    n = nt.nodes.new(typ)
    n.location = loc
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def link(nt, a, b):
    nt.links.new(a, b)


def math_node(nt, op, a=None, b=None, loc=(0, 0), clamp=False):
    n = node(nt, "ShaderNodeMath", loc, operation=op, use_clamp=clamp)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            link(nt, v, n.inputs[i])
    return n.outputs[0]


def add_driver(socket_owner, path, expr, variables=(), index=-1):
    fc = socket_owner.driver_add(path, index) if index >= 0 else socket_owner.driver_add(path)
    d = fc.driver
    d.type = "SCRIPTED"
    for name, kind, spec in variables:
        v = d.variables.new()
        v.name = name
        v.type = kind
        if kind == "LOC_DIFF":
            v.targets[0].id = spec[0]
            v.targets[1].id = spec[1]
        elif kind == "SINGLE_PROP":
            v.targets[0].id_type = spec[0]
            v.targets[0].id = spec[1]
            v.targets[0].data_path = spec[2]
    d.expression = expr
    return fc


def load_image(path, non_color=False):
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


# ---------------------------------------------------------------------------
# MAP SCENE
# ---------------------------------------------------------------------------

def setup_scene(scene, transparent=False, view="AgX"):
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y = RES_X, RES_Y
    r.resolution_percentage = RES_PCT
    r.fps = FPS
    r.film_transparent = transparent
    scene.eevee.taa_render_samples = 8 if RES_PCT <= 50 else 24
    scene.view_settings.view_transform = view
    scene.view_settings.look = "None"
    scene.frame_start = 1
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA" if transparent else "RGB"
    r.image_settings.color_depth = "8"


map_scene = bpy.context.scene
map_scene.name = "Map"
for ob in list(map_scene.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
setup_scene(map_scene)
map_scene.frame_end = T["map_end"]
map_scene.eevee.use_shadows = False   # normal-mapped relief reads the same; 2x faster
map_scene.eevee.shadow_resolution_scale = 1.0
map_scene.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in [
    i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items_static
] else "None"

world = bpy.data.worlds.new("MapWorld")
map_scene.world = world
world.use_nodes = True
bgn = world.node_tree.nodes["Background"]
bgn.inputs[0].default_value = (*BG, 1)
bgn.inputs[1].default_value = 1.0

# --- Camera rig -----------------------------------------------------------------
cam_data = bpy.data.cameras.new("MapCam")
cam_data.lens = 35
cam_data.clip_start = 0.1
cam_data.clip_end = 600
cam = bpy.data.objects.new("MapCam", cam_data)
map_scene.collection.objects.link(cam)
map_scene.camera = cam
target = bpy.data.objects.new("CamTarget", None)
map_scene.collection.objects.link(target)
tc = cam.constraints.new("TRACK_TO")
tc.target = target
tc.track_axis = "TRACK_NEGATIVE_Z"
tc.up_axis = "UP_Y"

for f, cl, tl in T["camera"]:
    cam.location = cl
    cam.keyframe_insert("location", frame=f)
    target.location = tl
    target.keyframe_insert("location", frame=f)
smooth_keys(cam)
smooth_keys(target)

# --- Fog node group (fades far terrain into the background) -----------------------
fog = bpy.data.node_groups.new("FogFactor", "ShaderNodeTree")
fog.interface.new_socket("Fog", in_out="OUTPUT", socket_type="NodeSocketFloat")
go = node(fog, "NodeGroupOutput", (800, 0))
camd = node(fog, "ShaderNodeCameraData", (-400, 0))
dist_val = node(fog, "ShaderNodeValue", (-400, -200))
dist_val.label = "cam_target_distance"
add_driver(dist_val.outputs[0], "default_value", "d",
           [("d", "LOC_DIFF", (cam, target))])
start = math_node(fog, "MULTIPLY", dist_val.outputs[0], 0.92, (-200, -200))
start = math_node(fog, "MAXIMUM", start, 16.0, (-100, -200))
span = math_node(fog, "MULTIPLY", dist_val.outputs[0], 0.75, (-200, -350))
span = math_node(fog, "MAXIMUM", span, 16.0, (-100, -350))
dz = math_node(fog, "SUBTRACT", camd.outputs["View Z Depth"], start, (0, 0))
f = math_node(fog, "DIVIDE", dz, span, (200, 0), clamp=True)
f = math_node(fog, "POWER", f, 1.2, (400, 0))
link(fog, f, go.inputs[0])

# --- Terrain mesh ---------------------------------------------------------------------
print("building terrain mesh")
zm = np.load(os.path.join(TEX, "height.npy"))
rows, cols = zm.shape
step = (LON1 - LON0) / cols
lon = LON0 + (np.arange(cols) + 0.5) * step
lat = LAT1 - (np.arange(rows) + 0.5) * ((LAT1 - LAT0) / rows)
X = np.asarray(project(lon, 0.0)[0])
Y = np.asarray(project(0.0, lat)[1])
XX, YY = np.meshgrid(X, Y)
co = np.stack([XX, YY, zm], axis=-1).reshape(-1, 3).astype(np.float32)
r_idx, c_idx = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing="ij")
v0 = (r_idx * cols + c_idx).ravel()
quads = np.stack([v0, v0 + cols, v0 + cols + 1, v0 + 1], axis=1).astype(np.int32)
nf = len(quads)
me = bpy.data.meshes.new("Terrain")
me.vertices.add(len(co))
me.vertices.foreach_set("co", co.ravel())
me.loops.add(nf * 4)
me.loops.foreach_set("vertex_index", quads.ravel())
me.polygons.add(nf)
me.polygons.foreach_set("loop_start", np.arange(nf, dtype=np.int32) * 4)
me.update(calc_edges=True)
uv = me.uv_layers.new(name="UVMap")
U = (lon - LON0) / (LON1 - LON0)
V = (lat - LAT0) / (LAT1 - LAT0)
UU, VV = np.meshgrid(U, V)
uvv = np.stack([UU, VV], -1).reshape(-1, 2)[quads.ravel()].astype(np.float32)
uv.data.foreach_set("uv", uvv.ravel())
me.shade_smooth()
terrain = bpy.data.objects.new("Terrain", me)
map_scene.collection.objects.link(terrain)

# Terrain material
mat = bpy.data.materials.new("TerrainMat")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = node(nt, "ShaderNodeOutputMaterial", (1400, 0))
texc = node(nt, "ShaderNodeTexCoord", (-1400, 0))
col_tex = node(nt, "ShaderNodeTexImage", (-1100, 300))
col_tex.image = load_image(os.path.join(TEX, "color.png"))
col_tex.interpolation = "Cubic"
nrm_tex = node(nt, "ShaderNodeTexImage", (-1100, -50))
nrm_tex.image = load_image(os.path.join(TEX, "normal.png"), non_color=True)
lit_tex = node(nt, "ShaderNodeTexImage", (-1100, -400))
lit_tex.image = load_image(os.path.join(TEX, "lights.png"), non_color=True)
lnd_tex = node(nt, "ShaderNodeTexImage", (-1100, -700))
lnd_tex.image = load_image(os.path.join(TEX, "land.png"), non_color=True)
for t in (col_tex, nrm_tex, lit_tex, lnd_tex):
    t.extension = "EXTEND"
    link(nt, texc.outputs["UV"], t.inputs[0])
nmap = node(nt, "ShaderNodeNormalMap", (-800, -50))
nmap.inputs["Strength"].default_value = 1.0
link(nt, nrm_tex.outputs[0], nmap.inputs["Color"])

night = node(nt, "ShaderNodeValue", (-1100, 600))
night.label = night.name = "night"
keys(night.outputs[0], "default_value", T["night"])

# darken base colour at night
dark = node(nt, "ShaderNodeMix", (-600, 300), data_type="RGBA", blend_type="MULTIPLY")
link(nt, night.outputs[0], dark.inputs["Factor"])
link(nt, col_tex.outputs[0], dark.inputs[6])
dark.inputs[7].default_value = (0.12, 0.12, 0.16, 1)

bsdf = node(nt, "ShaderNodeBsdfPrincipled", (-200, 200))
link(nt, dark.outputs[2], bsdf.inputs["Base Color"])
link(nt, nmap.outputs[0], bsdf.inputs["Normal"])
# water slightly glossy, land matte
rough = node(nt, "ShaderNodeMapRange", (-600, -300))
link(nt, lnd_tex.outputs[0], rough.inputs[0])
rough.inputs[3].default_value = 0.6
rough.inputs[4].default_value = 0.92
link(nt, rough.outputs[0], bsdf.inputs["Roughness"])
bsdf.inputs["Specular IOR Level"].default_value = 0.08

# city lights emission
lights_strength = math_node(nt, "MULTIPLY", lit_tex.outputs[0], night.outputs[0], (-600, -500))
lights_strength = math_node(nt, "MULTIPLY", lights_strength, 5.0, (-400, -500))
link(nt, lights_strength, bsdf.inputs["Emission Strength"])
bsdf.inputs["Emission Color"].default_value = (1.0, 0.42, 0.12, 1)

fog_grp = node(nt, "ShaderNodeGroup", (600, -300))
fog_grp.node_tree = fog
bg_em = node(nt, "ShaderNodeEmission", (600, -100))
bg_em.inputs[0].default_value = (*BG, 1)
# soft fade towards the map border (terrain only; lines have no UVs)
sxy = node(nt, "ShaderNodeSeparateXYZ", (300, -500))
link(nt, texc.outputs["UV"], sxy.inputs[0])
eu = math_node(nt, "PINGPONG", sxy.outputs[0], 0.5, (450, -450))
ev = math_node(nt, "PINGPONG", sxy.outputs[1], 0.5, (450, -600))
e = math_node(nt, "MINIMUM", eu, ev, (600, -500))
e = math_node(nt, "DIVIDE", e, 0.12, (750, -500), clamp=True)
e = math_node(nt, "SUBTRACT", 1.0, e, (900, -500))
fogt = math_node(nt, "MAXIMUM", fog_grp.outputs[0], e, (900, -300))
mix = node(nt, "ShaderNodeMixShader", (1000, 0))
link(nt, fogt, mix.inputs[0])
link(nt, bsdf.outputs[0], mix.inputs[1])
link(nt, bg_em.outputs[0], mix.inputs[2])
link(nt, mix.outputs[0], out.inputs[0])
terrain.data.materials.append(mat)

# Sun
sun_d = bpy.data.lights.new("Sun", "SUN")
sun_d.energy = 3.2
sun_d.angle = math.radians(2.5)
sun_d.color = (1.0, 0.97, 0.93)
sun = bpy.data.objects.new("Sun", sun_d)
sun.rotation_euler = (math.radians(52), 0, math.radians(-135))
map_scene.collection.objects.link(sun)
fill_d = bpy.data.lights.new("Fill", "SUN")
fill_d.energy = 0.35
fill_d.color = (0.55, 0.7, 1.0)
fill_d.use_shadow = False
fill = bpy.data.objects.new("Fill", fill_d)
fill.rotation_euler = (math.radians(30), 0, math.radians(60))
map_scene.collection.objects.link(fill)
keys(sun_d, "energy", T["sun_energy"])

# ---------------------------------------------------------------------------
# Route lines
# ---------------------------------------------------------------------------

def line_gn():
    ng = bpy.data.node_groups.new("RouteTube", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = node(ng, "NodeGroupInput", (-600, 0))
    go = node(ng, "NodeGroupOutput", (600, 0))
    m2c = node(ng, "GeometryNodeMeshToCurve", (-400, 0))
    circ = node(ng, "GeometryNodeCurvePrimitiveCircle", (-400, -200))
    circ.inputs["Resolution"].default_value = 6
    circ.name = "Profile"
    c2m = node(ng, "GeometryNodeCurveToMesh", (-100, 0))
    link(ng, gi.outputs["Geometry"], m2c.inputs["Mesh"])
    link(ng, m2c.outputs[0], c2m.inputs["Curve"])
    link(ng, circ.outputs["Curve"], c2m.inputs["Profile Curve"])
    setm = node(ng, "GeometryNodeSetMaterial", (200, 0))
    setm.name = "SetMat"
    link(ng, c2m.outputs[0], setm.inputs["Geometry"])
    link(ng, setm.outputs[0], go.inputs[0])
    return ng


ROUTE_GN = line_gn()


def line_material(name, base=1.0, head=4.0, head_len=0.6, soft=0.12, dash_period=0.0,
                  dash_duty=0.5, trail=0.0, phase=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.surface_render_method = "BLENDED"
    m.use_transparency_overlap = True
    nt = m.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (1600, 0))
    dist = node(nt, "ShaderNodeAttribute", (-1000, 0), attribute_type="GEOMETRY",
                attribute_name="dist").outputs["Fac"]
    reveal = node(nt, "ShaderNodeAttribute", (-1000, -200), attribute_type="OBJECT",
                  attribute_name="reveal").outputs["Fac"]
    opacity = node(nt, "ShaderNodeAttribute", (-1000, -400), attribute_type="OBJECT",
                   attribute_name="opacity").outputs["Fac"]
    behind = math_node(nt, "SUBTRACT", reveal, dist, (-800, 0))          # >0 = drawn
    grow = math_node(nt, "DIVIDE", behind, soft, (-600, 0), clamp=True)
    # bright leading head: exp(-behind/head_len), only where drawn
    hb = math_node(nt, "MAXIMUM", behind, 0.0, (-600, -200))
    hb = math_node(nt, "DIVIDE", hb, -head_len, (-400, -200))
    hb = math_node(nt, "EXPONENT", hb, None, (-200, -200))
    hb = math_node(nt, "MULTIPLY", hb, grow, (0, -200))
    alpha = grow
    if dash_period > 0:
        ph = math_node(nt, "DIVIDE", dist, dash_period, (-600, 300))
        ph = math_node(nt, "FRACT", ph, None, (-400, 300))
        dash = math_node(nt, "LESS_THAN", ph, dash_duty, (-200, 300))
        alpha = math_node(nt, "MULTIPLY", alpha, dash, (0, 200))
    if trail > 0:
        tf = math_node(nt, "DIVIDE", behind, trail, (-400, 500), clamp=True)
        tf = math_node(nt, "SUBTRACT", 1.0, tf, (-200, 500))
        tf = math_node(nt, "POWER", tf, 1.6, (0, 500))
        alpha = math_node(nt, "MULTIPLY", alpha, tf, (200, 300))
    # soft glow breathing
    breathe = node(nt, "ShaderNodeValue", (-400, -500))
    breathe.label = breathe.name = "breathe"
    add_driver(breathe.outputs[0], "default_value",
               f"0.78 + 0.22 * (0.5 + 0.5 * sin(frame * {2 * math.pi / 84:.5f} + {phase:.3f}))")
    strength = math_node(nt, "MULTIPLY", breathe.outputs[0], base, (0, -500))
    hstr = math_node(nt, "MULTIPLY", hb, head, (200, -200))
    strength = math_node(nt, "ADD", strength, hstr, (400, -400))
    fog_g = node(nt, "ShaderNodeGroup", (200, -700))
    fog_g.node_tree = fog
    vis = math_node(nt, "SUBTRACT", 1.0, fog_g.outputs[0], (400, -700))
    alpha = math_node(nt, "MULTIPLY", alpha, vis, (600, 0))
    alpha = math_node(nt, "MULTIPLY", alpha, opacity, (800, 0))
    em = node(nt, "ShaderNodeEmission", (800, -300))
    em.inputs[0].default_value = (1, 1, 1, 1)
    link(nt, strength, em.inputs["Strength"])
    tr = node(nt, "ShaderNodeBsdfTransparent", (800, -500))
    mix = node(nt, "ShaderNodeMixShader", (1300, 0))
    link(nt, alpha, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, em.outputs[0], mix.inputs[2])
    link(nt, mix.outputs[0], out.inputs[0])
    return m


def line_object(name, polylines, material, radius_k, radius_min, reveal_keys,
                opacity_keys=((1, 1.0),)):
    verts, edges, dist = [], [], []
    for pl in polylines:
        base = len(verts)
        for p in pl:
            verts.append((p[0], p[1], p[2]))
            dist.append(p[3])
        edges += [(base + i, base + i + 1) for i in range(len(pl) - 1)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    a = me.attributes.new("dist", "FLOAT", "POINT")
    a.data.foreach_set("value", dist)
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    map_scene.collection.objects.link(ob)
    mod = ob.modifiers.new("Tube", "NODES")
    mod.node_group = ROUTE_GN.copy()
    mod.node_group.name = "RouteTube_" + name
    mod.node_group.nodes["SetMat"].inputs["Material"].default_value = material
    # keep lines a constant on-screen thickness as the camera dollies
    add_driver(mod.node_group.nodes["Profile"].inputs["Radius"], "default_value",
               f"max({radius_min}, d * {radius_k})",
               [("d", "LOC_DIFF", (cam, target))])
    ob["reveal"] = 0.0
    ob["opacity"] = 1.0
    keys(ob, '["reveal"]', reveal_keys)
    keys(ob, '["opacity"]', opacity_keys)
    smooth_keys(ob)
    ob.visible_shadow = False
    return ob


print("building route lines")
m_border = line_material("Line_Border", base=1.6, head=6.0, head_len=0.8, phase=0.0)
m_net = line_material("Line_Network", base=0.9, head=5.0, head_len=0.5, phase=1.3)
m_glob = line_material("Line_Global", base=0.75, head=4.0, head_len=0.9, phase=2.6)
m_sea = line_material("Line_Sea", base=1.1, head=5.0, head_len=1.2, dash_period=0.32,
                      dash_duty=0.42, phase=3.9)
m_wake = line_material("Line_Wake", base=2.2, head=0.0, soft=0.05, trail=2.6, phase=0.0)

line_object("SaudiBorder", LINES["saudi_border"]["lines"], m_border, 0.0016, 0.022,
            T["reveal_border"])
line_object("SaudiNetwork", LINES["saudi_network"]["lines"], m_net, 0.0009, 0.012,
            T["reveal_saudi_net"], T["opacity_saudi_net"])
line_object("GlobalNetwork", LINES["global_network"]["lines"], m_glob, 0.0009, 0.012,
            T["reveal_global"], T["opacity_global"])
line_object("SeaLanes", LINES["sea_lanes"]["lines"], m_sea, 0.0012, 0.016,
            T["reveal_sea"])

# --- Ship -----------------------------------------------------------------------------
route = LINES["ship_route"]["lines"][0]
cum = [0.0]
for a, b in zip(route[:-1], route[1:]):
    cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
route_len = cum[-1]

cd = bpy.data.curves.new("ShipPath", "CURVE")
cd.dimensions = "3D"
sp = cd.splines.new("POLY")
sp.points.add(len(route) - 1)
for i, p in enumerate(route):
    sp.points[i].co = (p[0], p[1], 0.06, 1)
cd.use_path = True
cd.path_duration = 100
ship_path = bpy.data.objects.new("ShipPath", cd)
map_scene.collection.objects.link(ship_path)
ship_path.hide_render = True


def build_ship():
    bm = bmesh.new()
    L, Wd, Hh = 1.0, 0.16, 0.07
    outline = [(-L / 2, -Wd / 2), (L * 0.3, -Wd / 2), (L * 0.44, -Wd * 0.3), (L / 2, 0),
               (L * 0.44, Wd * 0.3), (L * 0.3, Wd / 2), (-L / 2, Wd / 2)]
    bot = [bm.verts.new((x * 0.97, y * 0.85, -Hh * 0.6)) for x, y in outline]
    top = [bm.verts.new((x, y, Hh)) for x, y in outline]
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    n = len(outline)
    for i in range(n):
        bm.faces.new((bot[i], bot[(i + 1) % n], top[(i + 1) % n], top[i]))

    def box(cx, cy, cz, sx, sy, sz):
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co.x = v.co.x * sx + cx
            v.co.y = v.co.y * sy + cy
            v.co.z = v.co.z * sz + cz
    # container stacks
    for i in range(9):
        x = -0.3 + i * 0.075
        for j, h in enumerate((0.05, 0.07, 0.06)):
            box(x, -0.045 + j * 0.045, Hh + h / 2, 0.065, 0.04, h)
    # bridge + funnel
    box(-0.42, 0, Hh + 0.07, 0.07, 0.15, 0.14)
    box(-0.42, 0, Hh + 0.16, 0.05, 0.17, 0.02)
    box(-0.47, 0, Hh + 0.1, 0.03, 0.04, 0.12)
    me = bpy.data.meshes.new("Ship")
    bm.to_mesh(me)
    bm.free()
    return me


ship_me = build_ship()
ship = bpy.data.objects.new("Ship", ship_me)
map_scene.collection.objects.link(ship)
ship.scale = (T["ship_scale"],) * 3
sm = bpy.data.materials.new("ShipBody")
sm.use_nodes = True
pb = sm.node_tree.nodes["Principled BSDF"]
pb.inputs["Base Color"].default_value = (0.02, 0.03, 0.05, 1)
pb.inputs["Roughness"].default_value = 0.5
pb.inputs["Emission Color"].default_value = (0.6, 0.75, 1.0, 1)
pb.inputs["Emission Strength"].default_value = 0.08
ship_me.materials.append(sm)
# glowing white edges
wire = bpy.data.objects.new("ShipWire", ship_me.copy())
map_scene.collection.objects.link(wire)
wire.parent = ship
wm = wire.modifiers.new("Wire", "WIREFRAME")
wm.thickness = 0.008
wm.use_replace = True
wmat = bpy.data.materials.new("ShipWire")
wmat.use_nodes = True
wnt = wmat.node_tree
wnt.nodes.clear()
we = node(wnt, "ShaderNodeEmission", (0, 0))
we.inputs[0].default_value = (1, 1, 1, 1)
we.inputs[1].default_value = 2.5
wo = node(wnt, "ShaderNodeOutputMaterial", (300, 0))
link(wnt, we.outputs[0], wo.inputs[0])
wire.data.materials.clear()
wire.data.materials.append(wmat)

fp = ship.constraints.new("FOLLOW_PATH")
fp.target = ship_path
fp.use_curve_follow = True
fp.use_fixed_location = True
fp.forward_axis = "FORWARD_X"
fp.up_axis = "UP_Z"
keys(fp, "offset_factor", T["ship_offset"])
smooth_keys(ship)
for o in (ship, wire):
    o.hide_render = False
keys(ship, "hide_render", [(1, True), (T["ship_show"], False)])
keys(wire, "hide_render", [(1, True), (T["ship_show"], False)])
for o in (ship, wire):
    for fc in iter_fcurves(o.animation_data.action):
        if fc.data_path == "hide_render":
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"

# wake: reveal follows the ship's position along the path
wake_pts = [[p[0], p[1], 0.05, c] for p, c in zip(route, cum)]
wake = line_object("ShipWake", [wake_pts], m_wake, 0.0016, 0.02, [(1, 0.0)])
wake.animation_data_clear()
add_driver(wake, '["reveal"]', f"o * {route_len:.4f} - 0.35",
           [("o", "SINGLE_PROP", ("OBJECT", ship, 'constraints["Follow Path"].offset_factor'))])

# --- Map compositor: bloom + gentle vignette -----------------------------------------------
def map_compositor(scene):
    ng = bpy.data.node_groups.new("MapComp", "CompositorNodeTree")
    scene.compositing_node_group = ng
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = node(ng, "CompositorNodeRLayers", (-600, 0))
    rl.scene = scene
    gl = node(ng, "CompositorNodeGlare", (-300, 0))
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Threshold"].default_value = 0.55
    gl.inputs["Strength"].default_value = 0.55
    gl.inputs["Size"].default_value = 0.55
    gl.inputs["Quality"].default_value = "High"
    link(ng, rl.outputs["Image"], gl.inputs["Image"])
    go = node(ng, "NodeGroupOutput", (200, 0))
    link(ng, gl.outputs["Image"], go.inputs[0])


map_compositor(map_scene)
map_scene.render.filepath = os.path.join(OUT, "frames_map", "")

# ---------------------------------------------------------------------------
# UI SCENE (orthographic overlay, 1 unit = 100 px at 1080x1920)
# ---------------------------------------------------------------------------
ui = bpy.data.scenes.new("UI")
setup_scene(ui, transparent=True, view="Standard")
ui.frame_end = T["end"]
ui.eevee.taa_render_samples = 8
ucam_d = bpy.data.cameras.new("UICam")
ucam_d.type = "ORTHO"
ucam_d.ortho_scale = 19.2
ucam = bpy.data.objects.new("UICam", ucam_d)
ucam.location = (0, 0, 20)
ui.collection.objects.link(ucam)
ui.camera = ucam
uw = bpy.data.worlds.new("UIWorld")
ui.world = uw
uw.use_nodes = True
uw.node_tree.nodes["Background"].inputs[1].default_value = 0.0

FONT_TITLE = bpy.data.fonts.load(os.path.join(FONTS, "Orbitron-SemiBold.ttf"))
FONT_BOLD = bpy.data.fonts.load(os.path.join(FONTS, "Orbitron-ExtraBold.ttf"))
FONT_SANS = bpy.data.fonts.load(os.path.join(FONTS, "Montserrat-SemiBold.ttf"))

_flat_cache = {}


def flat_material(color, image=None, name=None):
    """Unlit material; opacity from object colour alpha (keyable)."""
    key = (tuple(color), image)
    if key in _flat_cache:
        return _flat_cache[key]
    m = bpy.data.materials.new(name or "Flat")
    m.use_nodes = True
    m.surface_render_method = "BLENDED"
    nt = m.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (800, 0))
    oi = node(nt, "ShaderNodeObjectInfo", (-600, -200))
    em = node(nt, "ShaderNodeEmission", (200, 0))
    tr = node(nt, "ShaderNodeBsdfTransparent", (200, -200))
    mix = node(nt, "ShaderNodeMixShader", (500, 0))
    if image:
        tex = node(nt, "ShaderNodeTexImage", (-600, 200))
        tex.image = load_image(image)
        tex.interpolation = "Cubic"
        tex.extension = "CLIP"
        link(nt, tex.outputs["Color"], em.inputs[0])
        a = math_node(nt, "MULTIPLY", tex.outputs["Alpha"], oi.outputs["Alpha"], (-200, -100))
    else:
        em.inputs[0].default_value = (*color, 1)
        a = oi.outputs["Alpha"]
    link(nt, a, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, em.outputs[0], mix.inputs[2])
    link(nt, mix.outputs[0], out.inputs[0])
    _flat_cache[key] = m
    return m


def ui_link(ob):
    ui.collection.objects.link(ob)
    return ob


def opacity_keys(ob, fv):
    for f, v in fv:
        ob.color[3] = v
        ob.keyframe_insert("color", index=3, frame=f)


def image_plane(name, path, height, loc, z=0.0):
    img = load_image(path)
    w = height * img.size[0] / img.size[1]
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-w / 2, -height / 2, 0), (w / 2, -height / 2, 0),
                    (w / 2, height / 2, 0), (-w / 2, height / 2, 0)], [], [(0, 1, 2, 3)])
    uvl = me.uv_layers.new()
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uvl.data[i].uv = c
    me.materials.append(flat_material((1, 1, 1), path, name + "_mat"))
    ob = ui_link(bpy.data.objects.new(name, me))
    ob.location = (loc[0], loc[1], z)
    ob.color = (1, 1, 1, 0)
    return ob, w


def rect(name, w, h, color, loc, z=0.0, anchor_left=False):
    x0 = 0 if anchor_left else -w / 2
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x0, -h / 2, 0), (x0 + w, -h / 2, 0), (x0 + w, h / 2, 0), (x0, h / 2, 0)],
                   [], [(0, 1, 2, 3)])
    me.materials.append(flat_material(color))
    ob = ui_link(bpy.data.objects.new(name, me))
    ob.location = (loc[0], loc[1], z)
    ob.color = (1, 1, 1, 0)
    return ob


def disc(name, r, color, loc, z):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=True, radius=r, segments=160)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(flat_material(color))
    ob = ui_link(bpy.data.objects.new(name, me))
    ob.location = (loc[0], loc[1], z)
    ob.color = (1, 1, 1, 1)
    return ob


def text(name, body, size, font, color, loc, z=1.0, spacing=1.12, align="CENTER"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.font = font
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.space_character = spacing
    cu.materials.append(flat_material(color))
    ob = ui_link(bpy.data.objects.new(name, cu))
    ob.location = (loc[0], loc[1], z)
    ob.color = (1, 1, 1, 0)
    return ob


def reveal_text(ob, t_in, t_out, rise=0.28, dur=14, out_dur=10, drift=0.0):
    x, y, z = ob.location
    opacity_keys(ob, [(t_in, 0.0), (t_in + dur, 1.0), (t_out, 1.0), (t_out + out_dur, 0.0)])
    keys(ob, "location", [(t_in, (x, y - rise, z)), (t_in + dur, (x, y, z)),
                          (t_out, (x, y + drift, z)), (t_out + out_dur, (x, y + drift + rise * 0.6, z))])
    smooth_keys(ob)


# --- Vignette + twinkling plus-grid -----------------------------------------------------
vig_me = bpy.data.meshes.new("Vignette")
vig_me.from_pydata([(-5.6, -9.8, 0), (5.6, -9.8, 0), (5.6, 9.8, 0), (-5.6, 9.8, 0)], [], [(0, 1, 2, 3)])
vm = bpy.data.materials.new("Vignette")
vm.use_nodes = True
vm.surface_render_method = "BLENDED"
nt = vm.node_tree
nt.nodes.clear()
o = node(nt, "ShaderNodeOutputMaterial", (900, 0))
tc_ = node(nt, "ShaderNodeTexCoord", (-800, 0))
oi = node(nt, "ShaderNodeObjectInfo", (-800, -300))
sep = node(nt, "ShaderNodeSeparateXYZ", (-600, 0))
link(nt, tc_.outputs["Object"], sep.inputs[0])
ex = math_node(nt, "DIVIDE", sep.outputs[0], 6.5, (-400, 100))
ey = math_node(nt, "DIVIDE", sep.outputs[1], 10.5, (-400, -100))
ex = math_node(nt, "MULTIPLY", ex, ex, (-200, 100))
ey = math_node(nt, "MULTIPLY", ey, ey, (-200, -100))
r2 = math_node(nt, "ADD", ex, ey, (0, 0))
va = math_node(nt, "SUBTRACT", r2, 0.5, (150, 0))
va = math_node(nt, "MULTIPLY", va, 1.6, (300, 0), clamp=True)
# extra darkening at the bottom for title legibility
by = math_node(nt, "DIVIDE", sep.outputs[1], -9.6, (0, -250))
by = math_node(nt, "SUBTRACT", by, 0.15, (150, -250))
by = math_node(nt, "MULTIPLY", by, 0.9, (300, -250), clamp=True)
va = math_node(nt, "MAXIMUM", va, by, (450, 0))
va = math_node(nt, "MULTIPLY", va, oi.outputs["Alpha"], (600, 0))
em = node(nt, "ShaderNodeEmission", (450, -400))
em.inputs[0].default_value = (0, 0, 0, 1)
tr = node(nt, "ShaderNodeBsdfTransparent", (450, -550))
mx = node(nt, "ShaderNodeMixShader", (750, 0))
link(nt, va, mx.inputs[0])
link(nt, tr.outputs[0], mx.inputs[1])
link(nt, em.outputs[0], mx.inputs[2])
link(nt, mx.outputs[0], o.inputs[0])
vig_me.materials.append(vm)
vig = ui_link(bpy.data.objects.new("Vignette", vig_me))
vig.location.z = -1
vig.color = (1, 1, 1, 0.6)

# plus grid
bm = bmesh.new()
rng = np.random.default_rng(3)
rand_vals = []
for gx in np.arange(-5.0, 5.01, 1.0):
    for gy in np.arange(-9.0, 9.01, 1.0):
        rv = float(rng.random())
        s = 0.07 if rv > 0.85 else 0.035
        for (w, h) in ((s, 0.006), (0.006, s)):
            vs = [bm.verts.new((gx + dx, gy + dy, 0)) for dx, dy in
                  ((-w, -h), (w, -h), (w, h), (-w, h))]
            bm.faces.new(vs)
            rand_vals.append(rv)
pg_me = bpy.data.meshes.new("PlusGrid")
bm.to_mesh(pg_me)
bm.free()
ra = pg_me.attributes.new("rnd", "FLOAT", "FACE")
ra.data.foreach_set("value", rand_vals)
pm = bpy.data.materials.new("PlusGrid")
pm.use_nodes = True
pm.surface_render_method = "BLENDED"
nt = pm.node_tree
nt.nodes.clear()
o = node(nt, "ShaderNodeOutputMaterial", (900, 0))
rnd = node(nt, "ShaderNodeAttribute", (-800, 0), attribute_type="GEOMETRY", attribute_name="rnd").outputs["Fac"]
oi = node(nt, "ShaderNodeObjectInfo", (-800, -300))
tval = node(nt, "ShaderNodeValue", (-800, 200))
add_driver(tval.outputs[0], "default_value", "frame / 30.0")
ph = math_node(nt, "MULTIPLY", rnd, 6.283, (-600, 0))
sp_ = math_node(nt, "MULTIPLY", rnd, 1.6, (-600, 200))
sp_ = math_node(nt, "ADD", sp_, 0.7, (-450, 200))
tt = math_node(nt, "MULTIPLY", tval.outputs[0], sp_, (-300, 200))
tt = math_node(nt, "ADD", tt, ph, (-150, 100))
tw = math_node(nt, "SINE", tt, None, (0, 100))
tw = math_node(nt, "MULTIPLY", tw, 0.5, (150, 100))
tw = math_node(nt, "ADD", tw, 0.5, (300, 100))
tw = math_node(nt, "POWER", tw, 2.0, (450, 100))
a = math_node(nt, "MULTIPLY", tw, oi.outputs["Alpha"], (600, 0))
em = node(nt, "ShaderNodeEmission", (450, -300))
em.inputs[0].default_value = (0.25, 0.85, 0.78, 1)
tr = node(nt, "ShaderNodeBsdfTransparent", (450, -450))
mx = node(nt, "ShaderNodeMixShader", (750, 0))
link(nt, a, mx.inputs[0])
link(nt, tr.outputs[0], mx.inputs[1])
link(nt, em.outputs[0], mx.inputs[2])
link(nt, mx.outputs[0], o.inputs[0])
pg_me.materials.append(pm)
pgrid = ui_link(bpy.data.objects.new("PlusGrid", pg_me))
pgrid.location.z = -0.5
pgrid.color = (1, 1, 1, 0)
opacity_keys(pgrid, T["grid_opacity"])
smooth_keys(pgrid)

# --- Top-right logo -------------------------------------------------------------------------
top_logo, tlw = image_plane("TopLogo", os.path.join(LOGOS, "gplc_white.png"), 0.62,
                            (5.4 - 0.55 - 0, 8.45), z=2)
top_logo.location.x = 5.4 - 0.6 - tlw / 2
opacity_keys(top_logo, T["toplogo_opacity"])
x0 = top_logo.location.x
keys(top_logo, "location", [(T["toplogo_opacity"][0][0], (x0 + 0.25, 8.45, 2)),
                            (T["toplogo_opacity"][1][0], (x0, 8.45, 2))])
smooth_keys(top_logo)

# --- Titles ---------------------------------------------------------------------------------
TITLE_Y = -3.05
for i, (l1, l2, t_in, t_out) in enumerate(T["titles"]):
    a = text(f"Title{i}a", l1, 0.56, FONT_TITLE, (1, 1, 1), (0, TITLE_Y), spacing=1.18)
    b = text(f"Title{i}b", l2, 0.56, FONT_TITLE, (1, 1, 1), (0, TITLE_Y - 0.72), spacing=1.18)
    reveal_text(a, t_in, t_out)
    reveal_text(b, t_in + 5, t_out + 3)

# --- Progress bar ---------------------------------------------------------------------------
BAR_Y = -4.75
BAR_X0, BAR_X1 = -4.0, 4.0
pb_in, pb_out = T["bar"]
chev, cw = image_plane("BarChevron", os.path.join(LOGOS, "chevron_white.png"), 0.24,
                       (BAR_X0 - 0.3, BAR_Y), z=1)
star, sw = image_plane("BarStar", os.path.join(LOGOS, "star_white.png"), 0.2,
                       (BAR_X1 + 0.18, BAR_Y), z=1)
track = rect("BarTrack", BAR_X1 - BAR_X0, 0.018, (1, 1, 1), (BAR_X0, BAR_Y), z=0.9,
             anchor_left=True)
fillb = rect("BarFill", BAR_X1 - BAR_X0, 0.03, (1, 1, 1), (BAR_X0, BAR_Y), z=1.0,
             anchor_left=True)
for ob, peak in ((chev, 1.0), (star, 1.0), (track, 0.3), (fillb, 1.0)):
    opacity_keys(ob, [(pb_in, 0), (pb_in + 15, peak), (pb_out, peak), (pb_out + 12, 0)])
    smooth_keys(ob)
keys(track, "scale", [(pb_in, (0.0, 1, 1)), (pb_in + 20, (1, 1, 1))])
smooth_keys(track)
keys(fillb, "scale", [(f, (max(v, 0.0001), 1, 1)) for f, v in T["bar_fill"]])
smooth_keys(fillb)
keys(star, "rotation_euler", [(pb_in, (0, 0, -math.pi / 2)), (pb_in + 25, (0, 0, 0))])
smooth_keys(star)

# --- White wipe -----------------------------------------------------------------------------------
w0, w1 = T["wipe"]
grey = disc("WipeGrey", 1.0, (0.62, 0.64, 0.67), (5.8, -10.2), z=3.0)
white = disc("WipeWhite", 1.0, (1, 1, 1), (5.8, -10.2), z=3.1)
dark = disc("WipeDark", 1.0, (0.012, 0.016, 0.03), (-6.0, 10.4), z=3.05)
for ob, d in ((grey, 0), (white, 7)):
    keys(ob, "scale", [(w0 + d, (0.001,) * 3), (w1 + d, (26.0,) * 3)])
    smooth_keys(ob)
# counter-sweep arc from the top-left for a two-shape transition
keys(dark, "scale", [(w0 + 3, (0.001,) * 3), (w0 + 18, (5.0,) * 3), (w1, (0.001,) * 3)])
smooth_keys(dark)

# soft grey gradient on the white end background
gm = bpy.data.materials.new("EndGradient")
gm.use_nodes = True
nt = gm.node_tree
nt.nodes.clear()
o = node(nt, "ShaderNodeOutputMaterial", (800, 0))
tc_ = node(nt, "ShaderNodeTexCoord", (-600, 0))
sep = node(nt, "ShaderNodeSeparateXYZ", (-400, 0))
link(nt, tc_.outputs["Object"], sep.inputs[0])
dx = math_node(nt, "ADD", sep.outputs[0], 5.4, (-200, 100))
dy = math_node(nt, "SUBTRACT", sep.outputs[1], 9.6, (-200, -100))
dx = math_node(nt, "MULTIPLY", dx, dx, (0, 100))
dy = math_node(nt, "MULTIPLY", dy, dy, (0, -100))
rr = math_node(nt, "ADD", dx, dy, (150, 0))
rr = math_node(nt, "SQRT", rr, None, (300, 0))
rr = math_node(nt, "DIVIDE", rr, 9.0, (450, 0), clamp=True)
cr = node(nt, "ShaderNodeMix", (600, 0), data_type="RGBA")
link(nt, rr, cr.inputs["Factor"])
cr.inputs[6].default_value = (0.80, 0.81, 0.83, 1)
cr.inputs[7].default_value = (1, 1, 1, 1)
em = node(nt, "ShaderNodeEmission", (700, -200))
link(nt, cr.outputs[2], em.inputs[0])
link(nt, em.outputs[0], o.inputs[0])
grad_me = bpy.data.meshes.new("EndBG")
grad_me.from_pydata([(-5.6, -9.8, 0), (5.6, -9.8, 0), (5.6, 9.8, 0), (-5.6, 9.8, 0)], [], [(0, 1, 2, 3)])
grad_me.materials.append(gm)
grad = ui_link(bpy.data.objects.new("EndBG", grad_me))
grad.location.z = 3.2
keys(grad, "hide_render", [(1, True), (w1 + 7, False)])
for fc in iter_fcurves(grad.animation_data.action):
    for kp in fc.keyframe_points:
        kp.interpolation = "CONSTANT"

# --- Tagline -------------------------------------------------------------------------------------
ta, tb, tout = T["tagline"]
l1 = text("TagA", "ALL TRADE.", 0.58, FONT_BOLD, INK, (0, 0.42), z=4, spacing=1.15)
l2 = text("TagB", "NO TRADE-OFFS.", 0.58, FONT_BOLD, INK, (0, -0.42), z=4, spacing=1.15)
reveal_text(l1, ta, tout, rise=0.3, dur=16, out_dur=12, drift=0.0)
reveal_text(l2, tb, tout + 2, rise=0.3, dur=16, out_dur=12, drift=0.0)

# --- End card (logos from the original film) ----------------------------------------------------
e0 = T["endcard"]
ROW_Y = 0.35
emb, ew = image_plane("PIFEmblem", os.path.join(LOGOS, "pif_emblem.png"), 2.05, (-3.35, ROW_Y), z=4)
wmk, ww = image_plane("GPLCWordmark", os.path.join(LOGOS, "gplc_dark.png"), 1.3, (1.55, ROW_Y), z=4)
divd = rect("Divider", 0.028, 1.95, GOLD, (-1.85, ROW_Y), z=4)
tag = text("PIFTag", "A PIF COMPANY", 0.26, FONT_SANS, GREEN, (0, -6.85), z=4, spacing=1.08)

opacity_keys(emb, [(e0, 0), (e0 + 14, 1)])
keys(emb, "scale", [(e0, (0.86,) * 3), (e0 + 22, (1,) * 3)])
smooth_keys(emb)
opacity_keys(divd, [(e0 + 8, 0), (e0 + 12, 1)])
keys(divd, "scale", [(e0 + 8, (1, 0.001, 1)), (e0 + 24, (1, 1, 1))])
smooth_keys(divd)
opacity_keys(wmk, [(e0 + 14, 0), (e0 + 30, 1)])
keys(wmk, "location", [(e0 + 14, (1.55 - 0.6, ROW_Y, 4)), (e0 + 34, (1.55, ROW_Y, 4))])
smooth_keys(wmk)
reveal_text(tag, e0 + 30, T["end"] + 100, rise=0.15, dur=16)

ui.render.filepath = os.path.join(OUT, "frames_ui", "")

# ---------------------------------------------------------------------------
# EDIT SCENE: stack rendered frames, add original soundtrack, encode MP4
# ---------------------------------------------------------------------------
ed = bpy.data.scenes.new("Edit")
ed.render.resolution_x, ed.render.resolution_y = RES_X, RES_Y
ed.render.resolution_percentage = RES_PCT
ed.render.fps = FPS
ed.frame_start, ed.frame_end = 1, T["end"]
ed.view_settings.view_transform = "Standard"
se = ed.sequence_editor_create()


def add_seq(name, folder, n, channel, start=1):
    files = [f"{i:04d}.png" for i in range(1, n + 1)]
    st = se.strips.new_image(name, os.path.join(folder, files[0]), channel, start)
    for fn in files[1:]:
        st.elements.append(fn)
    return st


map_strip = add_seq("Map", os.path.join(OUT, "frames_map"), T["map_end"], 1)
ui_strip = add_seq("UI", os.path.join(OUT, "frames_ui"), T["end"], 2)
ui_strip.blend_type = "ALPHA_OVER"
audio = T.get("audio")
if audio and os.path.exists(audio):
    snd = se.strips.new_sound("Music", audio, 3, 1)
    snd.volume = 1.0
    if snd.frame_final_end > T["end"]:
        snd.frame_final_end = T["end"]
    keys(snd, "volume", [(T["end"] - 40, 1.0), (T["end"], 0.0)])

r = ed.render
r.filepath = os.path.join(OUT, "gplc_on_the_map.mp4")
try:
    r.image_settings.media_type = "VIDEO"
except Exception:
    pass
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"
r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"
r.ffmpeg.ffmpeg_preset = "GOOD"
r.ffmpeg.audio_codec = "AAC"
r.ffmpeg.audio_bitrate = 192

blend = os.path.join(OUT, "gplc_on_the_map.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
print("saved", blend)
