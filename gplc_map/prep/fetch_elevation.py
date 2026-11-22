"""Download AWS Terrarium elevation tiles (land + bathymetry) and reproject them
to an equirectangular 16-bit heightmap covering the map region.

Usage: python3 fetch_elevation.py <data_dir> [zoom]
Writes <data_dir>/elevation.npy (float32 metres) and elevation_preview.png.
"""
import io
import math
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LON0, LON1, LAT0, LAT1, DEG_PER_PX  # noqa: E402

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def fetch(args):
    z, x, y, cache = args
    path = os.path.join(cache, f"{z}_{x}_{y}.png")
    if not os.path.exists(path):
        for attempt in range(4):
            try:
                with urllib.request.urlopen(URL.format(z=z, x=x, y=y), timeout=60) as r:
                    data = r.read()
                with open(path, "wb") as f:
                    f.write(data)
                break
            except Exception:
                if attempt == 3:
                    raise
    return (x, y, path)


def main():
    data_dir = sys.argv[1]
    z = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    cache = os.path.join(data_dir, "tiles")
    os.makedirs(cache, exist_ok=True)

    x0, y0 = lonlat_to_tile(LON0, LAT1, z)
    x1, y1 = lonlat_to_tile(LON1, LAT0, z)
    xs = range(int(x0), int(x1) + 1)
    ys = range(int(y0), int(y1) + 1)
    jobs = [(z, x, y, cache) for x in xs for y in ys]
    print(f"fetching {len(jobs)} tiles at z{z}")
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(fetch, jobs))

    # Assemble mercator mosaic.
    W = len(xs) * 256
    H = len(ys) * 256
    mosaic = np.zeros((H, W), np.float32)
    for x, y, path in results:
        im = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
        elev = im[..., 0] * 256.0 + im[..., 1] + im[..., 2] / 256.0 - 32768.0
        mosaic[(y - ys[0]) * 256:(y - ys[0] + 1) * 256,
               (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = elev

    # Reproject to equirectangular (bilinear).
    out_w = int(round((LON1 - LON0) / DEG_PER_PX))
    out_h = int(round((LAT1 - LAT0) / DEG_PER_PX))
    lons = LON0 + (np.arange(out_w) + 0.5) * DEG_PER_PX
    lats = LAT1 - (np.arange(out_h) + 0.5) * DEG_PER_PX
    n = 2 ** z
    px = ((lons + 180.0) / 360.0 * n - xs[0]) * 256.0 - 0.5
    py = ((1.0 - np.arcsinh(np.tan(np.radians(lats))) / math.pi) / 2.0 * n - ys[0]) * 256.0 - 0.5
    PX, PY = np.meshgrid(px, py)
    ix = np.clip(np.floor(PX).astype(int), 0, W - 2)
    iy = np.clip(np.floor(PY).astype(int), 0, H - 2)
    fx = np.clip(PX - ix, 0, 1)
    fy = np.clip(PY - iy, 0, 1)
    a = mosaic[iy, ix]
    b = mosaic[iy, ix + 1]
    c = mosaic[iy + 1, ix]
    d = mosaic[iy + 1, ix + 1]
    out = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
    np.save(os.path.join(data_dir, "elevation.npy"), out.astype(np.float32))

    prev = np.clip((out + 6000) / 12000, 0, 1)
    Image.fromarray((prev * 255).astype(np.uint8)).resize((out_w // 4, out_h // 4)).save(
        os.path.join(data_dir, "elevation_preview.png"))
    print("elevation", out.shape, float(out.min()), float(out.max()))


if __name__ == "__main__":
    main()
