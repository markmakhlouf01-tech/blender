"""Extract a country's outer border (mainland exterior ring only) from Natural Earth.

    python build_border.py DATA_DIR [ISO_A3=SAU]

Writes DATA_DIR/border_<iso>.json: [[lon, lat], ...], closed, lightly simplified.
"""
import io
import json
import math
import os
import sys
import urllib.request
import zipfile

import shapefile

DATA = sys.argv[1]
ISO = sys.argv[2] if len(sys.argv) > 2 else "SAU"
NAME = "ne_10m_admin_0_countries"
zpath = os.path.join(DATA, NAME + ".zip")
if not os.path.exists(zpath):
    with urllib.request.urlopen(f"https://naciscdn.org/naturalearth/10m/cultural/{NAME}.zip", timeout=120) as r:
        open(zpath, "wb").write(r.read())
zf = zipfile.ZipFile(zpath)
sf = shapefile.Reader(shp=io.BytesIO(zf.read(NAME + ".shp")), shx=io.BytesIO(zf.read(NAME + ".shx")),
                      dbf=io.BytesIO(zf.read(NAME + ".dbf")))
fields = [f[0] for f in sf.fields[1:]]
for rec, shp in zip(sf.records(), sf.shapes()):
    d = dict(zip(fields, rec))
    if ISO in (d.get("ADM0_A3"), d.get("ISO_A3"), d.get("SOV_A3")):
        break
else:
    sys.exit(f"{ISO} not found")


def area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2


parts = list(shp.parts) + [len(shp.points)]
rings = [shp.points[a:b] for a, b in zip(parts[:-1], parts[1:])]
ring = max(rings, key=area)  # mainland; islands and holes dropped


def simplify(pts, tol):
    """Douglas-Peucker in degrees."""
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / n
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)


# Start the trace at the point nearest Riyadh's longitude on the northern border, for a clean draw-on.
ring = [list(p) for p in ring[:-1]] if ring[0] == ring[-1] else [list(p) for p in ring]
start = max(range(len(ring)), key=lambda i: ring[i][1] - abs(ring[i][0] - 43.0) * 0.5)
ring = ring[start:] + ring[:start]
half = len(ring) // 2  # split: a closed ring has coincident ends
ring = simplify(ring[:half + 1], 0.01)[:-1] + simplify(ring[half:] + [ring[0]], 0.01)
json.dump(ring, open(os.path.join(DATA, f"border_{ISO.lower()}.json"), "w"))
print(ISO, d.get("NAME"), len(ring), "points")
