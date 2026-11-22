"""Bake map textures from the elevation grid + Natural Earth data.

Usage: python3 build_textures.py <data_dir>
Needs <data_dir>/elevation.npy and <data_dir>/shp/*.shp.
Writes into <data_dir>/tex/:
  color.png    base colour (sRGB): charcoal land, navy ocean with lighter shelves
  normal.png   tangent-space relief normal map (exaggerated)
  lights.png   night city-lights mask (grey)
  height.npy   displacement heights in Blender units (downsampled mesh grid)
"""
import math
import os
import sys

import numpy as np
import shapefile
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LON0, LAT1, DEG_PER_PX, X_SCALE  # noqa: E402

D = sys.argv[1]
OUT = os.path.join(D, "tex")
os.makedirs(OUT, exist_ok=True)

Z_LAND = 0.13 / 1000.0      # BU per metre on land (~15x exaggeration)
Z_SEA = 0.045 / 1000.0      # flatter sea floor so routes read at sea level
MESH_STEP = 4               # heightmap px per mesh vertex

elev = np.load(os.path.join(D, "elevation.npy"))
H, W = elev.shape


def to_px(lon, lat):
    return ((lon - LON0) / DEG_PER_PX, (LAT1 - lat) / DEG_PER_PX)


def rasterize(shp, ss=1, filt=None):
    img = Image.new("L", (W * ss, H * ss), 0)
    dr = ImageDraw.Draw(img)
    r = shapefile.Reader(shp)
    for rec, shape in zip(r.iterRecords(), r.iterShapes()):
        if filt and not filt(rec):
            continue
        parts = list(shape.parts) + [len(shape.points)]
        for i in range(len(parts) - 1):
            pts = shape.points[parts[i]:parts[i + 1]]
            if len(pts) < 3:
                continue
            dr.polygon([(x * ss, y * ss) for x, y in (to_px(*p) for p in pts)], fill=255)
    if ss > 1:
        img = img.resize((W, H), Image.BILINEAR)
    return np.asarray(img, np.float32) / 255.0


print("land mask")
land = rasterize(os.path.join(D, "shp/ne_10m_admin_0_countries.shp"))
lakes = rasterize(os.path.join(D, "shp/ne_10m_lakes.shp"))
land = np.clip(land - lakes, 0, 1)
land = np.asarray(Image.fromarray((land * 255).astype(np.uint8)).filter(
    ImageFilter.GaussianBlur(1.0)), np.float32) / 255.0

# --- Heights (BU) -----------------------------------------------------------
e_land = np.maximum(elev, 0.0)
e_sea = np.minimum(elev, 0.0)
z = land * (e_land * Z_LAND + 0.01) + (1 - land) * np.minimum(e_sea * Z_SEA, -0.01)
z = z.astype(np.float32)
zm = z[::MESH_STEP, ::MESH_STEP]
np.save(os.path.join(OUT, "height.npy"), zm)
np.save(os.path.join(OUT, "height_full.npy"), z)
print("mesh grid", zm.shape)

def blur(a, sigma):
    r = int(math.ceil(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 1, a)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 0, a)


# --- Normal map ---------------------------------------------------------------
dx = DEG_PER_PX * X_SCALE
dy = DEG_PER_PX
zs = z * 2.2                      # extra shading exaggeration
zs = blur(zs, 0.6)
gx = np.gradient(zs, axis=1) / dx
gy = -np.gradient(zs, axis=0) / dy          # image rows go south
n = np.dstack([-gx, -gy, np.ones_like(gx)])
n /= np.linalg.norm(n, axis=2, keepdims=True)
Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8)).save(os.path.join(OUT, "normal.png"))

# --- Base colour -------------------------------------------------------------
def srgb(c):
    return np.array(c, np.float32) / 255.0


depth = np.clip(-elev / 6000.0, 0, 1)
shelf = np.clip(1 - (-elev) / 220.0, 0, 1) ** 1.5      # bright shallow water
ocean = (srgb((24, 52, 92)) * (1 - depth[..., None]) + srgb((6, 16, 34)) * depth[..., None])
ocean = ocean + shelf[..., None] * (srgb((40, 92, 148)) - ocean) * 0.65
hl = np.clip(elev / 3500.0, 0, 1)[..., None]
land_c = srgb((38, 40, 44)) * (1 - hl) + srgb((62, 63, 66)) * hl
col = ocean * (1 - land[..., None]) + land_c * land[..., None]
Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(os.path.join(OUT, "color.png"))
Image.fromarray((land * 255).astype(np.uint8)).save(os.path.join(OUT, "land.png"))

# --- Night lights ------------------------------------------------------------
print("lights")
layers = {k: Image.new("F", (W, H), 0.0) for k in ("core", "halo", "sub")}
drw = {k: ImageDraw.Draw(v) for k, v in layers.items()}
r = shapefile.Reader(os.path.join(D, "shp/ne_10m_populated_places_simple.shp"))
fields = [f[0] for f in r.fields[1:]]
ip = fields.index("pop_max")
rng = np.random.default_rng(7)
places = sorted(((max(rec[ip], 1000), shp.points[0]) for rec, shp in
                 zip(r.iterRecords(), r.iterShapes())), key=lambda t: t[0])
for pop, (lon, lat) in places:                      # ascending: big cities on top
    x, y = to_px(lon, lat)
    if not (0 <= x < W and 0 <= y < H):
        continue
    p = math.log10(pop / 1000.0)                    # 0 (1k) .. ~4.5 (30M)
    big = max(0.0, p - 2.5)                         # > ~300k
    rad = 0.55 + 0.45 * p + 1.1 * big ** 1.4
    val = min(1.0, 0.04 + 0.11 * p + 0.3 * big)
    drw["core"].ellipse([x - rad, y - rad, x + rad, y + rad], fill=val)
    if big > 0.2:                                   # soft halo around major cities
        hr = rad * 3.0
        drw["halo"].ellipse([x - hr, y - hr, x + hr, y + hr], fill=val * 0.22)
        for _ in range(int(min(60, pop / 120000))):  # suburbs / satellite towns
            ox, oy = rng.normal(0, rad * 1.6, 2)
            rr = rng.uniform(0.5, 1.2)
            drw["sub"].ellipse([x + ox - rr, y + oy - rr, x + ox + rr, y + oy + rr], fill=val * 0.35)
halo = blur(np.asarray(layers["halo"]), 4.0)
lights_arr = np.maximum(np.asarray(layers["core"]), np.asarray(layers["sub"])) + halo
roads = Image.new("F", (W, H), 0.0)
rd = ImageDraw.Draw(roads)
r = shapefile.Reader(os.path.join(D, "shp/ne_10m_roads.shp"))
for shp in r.iterShapes():
    parts = list(shp.parts) + [len(shp.points)]
    for i in range(len(parts) - 1):
        pts = [to_px(*p) for p in shp.points[parts[i]:parts[i + 1]]]
        if len(pts) > 1:
            rd.line(pts, fill=0.035, width=1)
l = lights_arr + np.asarray(roads)
l = blur(l, 1.2)
l = l * land
l = np.clip(l * 1.3, 0, 1) ** 1.2
Image.fromarray((l * 255).astype(np.uint8)).save(os.path.join(OUT, "lights.png"))
print("textures ok")
