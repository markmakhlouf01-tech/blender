"""Build the equirectangular Earth colour map for the globe.

    python build_earth.py DATA_DIR [WIDTH]

Downloads AWS Terrarium elevation tiles (z5 world, z6 over Africa / Middle East /
South Asia where the camera gets close) and Natural Earth 10m land + lakes, then
writes DATA_DIR/earth_color.png (WIDTH x WIDTH/2, default 16384) and earth_color_4k.png: relief-shaded
dark land, teal shallows over bathymetry, pale ice caps.
"""
import io
import math
import os
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import shapefile
from PIL import Image, ImageDraw
from scipy import ndimage

DATA = sys.argv[1]
W = int(sys.argv[2]) if len(sys.argv) > 2 else 16384
H = W // 2
TILE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
NE = "https://naciscdn.org/naturalearth/10m/physical/{}.zip"
DETAIL = (-25.0, 155.0, -48.0, 50.0)  # lon0, lon1, lat0, lat1 fetched at z6

os.makedirs(os.path.join(DATA, "tiles"), exist_ok=True)


def get(url, path):
    if not os.path.exists(path):
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = r.read()
                break
            except Exception:
                if attempt == 4:
                    raise
        with open(path, "wb") as f:
            f.write(data)
    return path


def tile_xy(lon, lat, z):
    n = 2 ** z
    lat = max(min(lat, 85.0), -85.0)
    return ((lon + 180) / 360 * n,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def mosaic(z, lon0, lon1, lat0, lat1):
    x0, y0 = tile_xy(lon0, lat1, z)
    x1, y1 = tile_xy(lon1, lat0, z)
    xs = range(int(x0), min(int(x1), 2 ** z - 1) + 1)
    ys = range(int(y0), min(int(y1), 2 ** z - 1) + 1)
    jobs = [(x, y) for x in xs for y in ys]
    print(f"z{z}: {len(jobs)} tiles", flush=True)

    def fetch(xy):
        x, y = xy
        return xy, get(TILE.format(z=z, x=x, y=y), os.path.join(DATA, "tiles", f"{z}_{x}_{y}.png"))

    m = np.zeros((len(ys) * 256, len(xs) * 256), np.float32)
    with ThreadPoolExecutor(16) as ex:
        for (x, y), p in ex.map(fetch, jobs):
            a = np.asarray(Image.open(p).convert("RGB"), np.float32)
            m[(y - ys[0]) * 256:(y - ys[0] + 1) * 256, (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = \
                a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    return m, xs[0], ys[0]


def sample(m, x0, y0, z, lons, lats):
    n = 2 ** z
    px = ((lons + 180) / 360 * n - x0) * 256 - 0.5
    lat = np.clip(lats, -85, 85)
    py = ((1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * n - y0) * 256 - 0.5
    PX, PY = np.meshgrid(px, py)
    return ndimage.map_coordinates(m, [PY, PX], order=1, mode="nearest").astype(np.float32)


lons = -180 + (np.arange(W) + 0.5) * 360 / W
lats = 90 - (np.arange(H) + 0.5) * 180 / H

m, x0, y0 = mosaic(5, -180, 179.999, -85, 85)
elev = sample(m, x0, y0, 5, lons, lats)
del m
lo0, lo1, la0, la1 = DETAIL
ci = np.where((lons >= lo0) & (lons <= lo1))[0]
ri = np.where((lats >= la0) & (lats <= la1))[0]
m, x0, y0 = mosaic(6, lo0, lo1, la0, la1)
elev[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1] = sample(m, x0, y0, 6, lons[ci], lats[ri])
del m
# Tiles stop at +-85 deg: Arctic Ocean / Antarctic plateau beyond.
elev[lats > 84.5] = -3000
elev[lats < -84.5] = 2800
print("elevation", elev.shape, flush=True)


def rasterize(name, scale=1):
    z = get(NE.format(name), os.path.join(DATA, name + ".zip"))
    zf = zipfile.ZipFile(z)
    stem = name
    r = shapefile.Reader(shp=io.BytesIO(zf.read(stem + ".shp")), shx=io.BytesIO(zf.read(stem + ".shx")),
                         dbf=io.BytesIO(zf.read(stem + ".dbf")))
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    for shp in r.shapes():
        pts = shp.points
        parts = list(shp.parts) + [len(pts)]
        for a, b in zip(parts[:-1], parts[1:]):
            ring = [((x + 180) / 360 * W, (90 - y) / 180 * H) for x, y in pts[a:b]]
            if len(ring) > 2:
                d.polygon(ring, fill=255)
    return np.asarray(img, np.float32) / 255


land = rasterize("ne_10m_land")
land = np.maximum(land - rasterize("ne_10m_lakes"), 0)
land = ndimage.gaussian_filter(land, 0.7)
print("masks", flush=True)

coast = ndimage.gaussian_filter(land, W / 4096 * 3)
LON = lons[None, :]
L = np.array([-0.55, 0.55, 0.63])
L /= np.linalg.norm(L)
px_m = 40075000 / W
EX = 9.0  # relief exaggeration so terrain reads from orbit


def lerp(a, b, t):
    return a + (b - a) * t[..., None]


def rgb(*c):
    return np.array(c, np.float32)


def shade_rows(r0, r1):
    """Hillshade (light from the north-west), 0 on flat ground."""
    a, b = max(r0 - 1, 0), min(r1 + 1, H)
    e = elev[a:b]
    gy, gx = np.gradient(e)
    gx /= px_m * np.cos(np.radians(lats[a:b]))[:, None].clip(0.05)
    gy /= px_m
    nx, ny = -gx * EX, gy * EX
    s = (nx * L[0] + ny * L[1] + L[2]) / np.sqrt(nx * nx + ny * ny + 1)
    return ((s - L[2]) * 1.8)[r0 - a:r0 - a + (r1 - r0)]


out = np.empty((H, W, 3), np.uint8)
for r0 in range(0, H, 512):
    r1 = min(r0 + 512, H)
    e, ld, sh = elev[r0:r1], land[r0:r1], shade_rows(r0, r1)
    lat = lats[r0:r1, None]
    # Land: dark neutral grey, slightly lighter on plateaus, strong relief.
    h = np.clip(e / 3000, 0, 1)
    c_land = lerp(rgb(0.25, 0.26, 0.27) + 0 * h[..., None], rgb(0.34, 0.34, 0.35), h)
    c_land *= np.clip(1 + sh * 1.3, 0.3, 2.2)[..., None]
    # Water: teal shallows -> deep blue-teal, with soft bathymetry relief and a coastal glow.
    t = np.clip(np.log1p(np.clip(-e, 0, None) / 25) / np.log1p(5500 / 25), 0, 1)
    shallow, mid, deep = rgb(0.30, 0.62, 0.62), rgb(0.17, 0.40, 0.43), rgb(0.09, 0.21, 0.26)
    c_w = np.where((t < 0.45)[..., None], lerp(shallow + 0 * t[..., None], mid, t / 0.45),
                   lerp(mid + 0 * t[..., None], deep, (t - 0.45) / 0.55))
    c_w *= np.clip(1 + sh * 0.35, 0.6, 1.4)[..., None]
    c_w += rgb(0.10, 0.26, 0.26) * (np.clip(coast[r0:r1] * 2, 0, 1) * (1 - ld))[..., None]
    c = lerp(c_w, c_land, ld)
    # Ice: Antarctica and Greenland.
    greenland = (lat > 59) & (LON < -11) & ((LON > -58) | ((lat > 75.5) & (LON > -73)))
    ice = ((lat < -61) | greenland | (lat > 80)) * ld
    c = lerp(c, rgb(0.72, 0.76, 0.80) * np.clip(1 + sh * 0.5, 0.6, 1.3)[..., None], ice * 0.9)
    out[r0:r1] = (np.clip(c, 0, 1) * 255 + 0.5).astype(np.uint8)  # colours are sRGB values

im = Image.fromarray(out)
im.save(os.path.join(DATA, "earth_color.png"), compress_level=3)
im.resize((4096, 2048), Image.LANCZOS).save(os.path.join(DATA, "earth_color_4k.png"))  # for wide shots
im.resize((2048, 1024), Image.LANCZOS).save(os.path.join(DATA, "earth_preview.png"))
print("done", flush=True)
