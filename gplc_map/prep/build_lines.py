"""Build route-line geometry (Blender coords) with a per-point 'dist' value
that drives the draw-on animation (lines grow outward from hubs).

Usage: python3 build_lines.py <data_dir>
Writes <data_dir>/lines.json:
  {group: {"lines": [[[x,y,z,dist], ...], ...], "max_dist": float}}
"""
import heapq
import json
import math
import os
import sys

import numpy as np
import shapefile
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LON0, LON1, LAT0, LAT1, DEG_PER_PX, project  # noqa: E402

D = sys.argv[1]
Z = np.load(os.path.join(D, "tex/height_full.npy"))
LAND = np.asarray(Image.open(os.path.join(D, "tex/land.png")), np.float32) / 255.0
H, W = Z.shape


def _blur(a, sigma):
    r = int(math.ceil(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 1, a)
    return np.apply_along_axis(lambda v: np.convolve(np.pad(v, r, mode="edge"), k, "valid"), 0, a)


LANDB = _blur(LAND[::4, ::4], 3.0)          # ~0.3 deg falloff, quarter res
LANDB = np.kron(LANDB, np.ones((4, 4), np.float32))[:H, :W]
STEP = 0.06          # resample spacing in BU
LIFT = 0.035         # height above terrain

HUBS = {
    "riyadh": (46.72, 24.69), "jeddah": (39.17, 21.54), "dammam": (50.10, 26.43),
    "neom": (35.25, 28.0),
}


def px(lon, lat):
    return (lon - LON0) / DEG_PER_PX, (LAT1 - lat) / DEG_PER_PX


def zmax(lon, lat, r=3):
    x, y = px(lon, lat)
    x, y = int(round(x)), int(round(y))
    x0, x1 = max(0, x - r), min(W, x + r + 1)
    y0, y1 = max(0, y - r), min(H, y + r + 1)
    if x0 >= x1 or y0 >= y1:
        return 0.0
    return float(Z[y0:y1, x0:x1].max())


def is_land(lon, lat):
    x, y = px(lon, lat)
    x, y = int(x), int(y)
    if 0 <= x < W and 0 <= y < H:
        return LAND[y, x] > 0.5
    return False


def inside(lon, lat, m=0.5):
    return LON0 + m < lon < LON1 - m and LAT0 + m < lat < LAT1 - m


def read_parts(path, filt=None):
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields[1:]]
    for rec, shp in zip(r.iterRecords(), r.iterShapes()):
        rd = dict(zip(names, rec))
        if filt and not filt(rd):
            continue
        parts = list(shp.parts) + [len(shp.points)]
        for i in range(len(parts) - 1):
            yield rd, shp.points[parts[i]:parts[i + 1]]


def resample(lonlat, step_deg):
    """Densify a lon/lat polyline to ~step spacing (Blender units ~ degrees)."""
    out = [lonlat[0]]
    for (a, b), (c, d) in zip(lonlat[:-1], lonlat[1:]):
        n = max(1, int(math.hypot(c - a, d - b) / step_deg))
        for k in range(1, n + 1):
            t = k / n
            out.append((a + (c - a) * t, b + (d - b) * t))
    return out


def chaikin(pts, it=2):
    for _ in range(it):
        new = [pts[0]]
        for p, q in zip(pts[:-1], pts[1:]):
            new.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            new.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        new.append(pts[-1])
        pts = new
    return pts


def bu_dist(a, b):
    xa, ya = project(*a)
    xb, yb = project(*b)
    return math.hypot(xb - xa, yb - ya)


# ---------------------------------------------------------------------------
def network(polylines, hub, virtual_cost=1.35, snap=1e-3):
    """Dijkstra over a snapped polyline graph. Every node also gets a virtual
    edge from the hub (euclidean * virtual_cost) so disconnected pieces still
    start in a sensible radial order."""
    key = lambda p: (round(p[0] / snap), round(p[1] / snap))
    coords, adj = {}, {}
    for pl in polylines:
        for a, b in zip(pl[:-1], pl[1:]):
            ka, kb = key(a), key(b)
            if ka == kb:
                continue
            coords[ka], coords[kb] = a, b
            w = bu_dist(a, b)
            adj.setdefault(ka, []).append((kb, w))
            adj.setdefault(kb, []).append((ka, w))
    dist = {k: bu_dist(hub, c) * virtual_cost for k, c in coords.items()}
    pq = [(d, k) for k, d in dist.items()]
    heapq.heapify(pq)
    while pq:
        d, k = heapq.heappop(pq)
        if d > dist[k]:
            continue
        for nb, w in adj.get(k, ()):
            nd = d + w
            if nd < dist[nb]:
                dist[nb] = nd
                heapq.heappush(pq, (nd, nb))
    return lambda p: dist[key(p)]


def components(polylines, min_len, snap=2e-2):
    """Drop connected pieces of a network whose total length is below min_len."""
    key = lambda p: (round(p[0] / snap), round(p[1] / snap))
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for pl in polylines:
        for a, b in zip(pl[:-1], pl[1:]):
            ra, rb = find(key(a)), find(key(b))
            if ra != rb:
                parent[ra] = rb
    total = {}
    for pl in polylines:
        L = sum(bu_dist(a, b) for a, b in zip(pl[:-1], pl[1:]))
        r = find(key(pl[0]))
        total[r] = total.get(r, 0) + L
    return [pl for pl in polylines if total[find(key(pl[0]))] >= min_len]


def push_to_sea(pts, target=0.18, iters=60):
    """Move lane points that sit on/near land out to open water."""
    out = []
    for lon, lat in pts:
        if 31.9 < lon < 33.0 and 29.7 < lat < 31.5:      # Suez Canal is meant to be on land
            out.append((lon, lat))
            continue
        for _ in range(iters):
            x, y = px(lon, lat)
            xi, yi = int(np.clip(x, 1, W - 2)), int(np.clip(y, 1, H - 2))
            if LANDB[yi, xi] <= target:
                break
            gx = LANDB[yi, xi + 1] - LANDB[yi, xi - 1]
            gy = LANDB[yi + 1, xi] - LANDB[yi - 1, xi]
            n = math.hypot(gx, gy) or 1.0
            lon -= gx / n * 0.04
            lat += gy / n * 0.04
        out.append((lon, lat))
    return out


def emit(polylines, dist_fn, lift=LIFT, sea=False):
    out = []
    for pl in polylines:
        dense = resample(pl, STEP)
        # dist for dense points: interpolate between original vertices
        dv = []
        orig_d = [dist_fn(p) for p in pl]
        seg_lens = [bu_dist(a, b) for a, b in zip(pl[:-1], pl[1:])]
        # walk dense points along segments
        j, acc = 0, 0.0
        for i, p in enumerate(dense):
            while j < len(seg_lens) - 1 and bu_dist(pl[j], p) > seg_lens[j] + 1e-9:
                j += 1
            if not seg_lens:
                dv.append(orig_d[0])
                continue
            t = min(1.0, bu_dist(pl[j], p) / max(seg_lens[j], 1e-9))
            dv.append(orig_d[j] * (1 - t) + orig_d[j + 1] * t)
        pts = []
        for (lon, lat), d in zip(dense, dv):
            x, y = project(lon, lat)
            z = (0.03 if sea else max(zmax(lon, lat), 0.0) + lift)
            pts.append([round(x, 4), round(y, 4), round(z, 4), round(d, 4)])
        if len(pts) > 1:
            out.append(pts)
    return out


def simplify(pts, tol):
    """Douglas-Peucker on lon/lat."""
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    L = np.hypot(*ab)
    P = np.array(pts)
    if L < 1e-12:
        d = np.hypot(*(P - a).T)
    else:
        d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > tol:
        return simplify(pts[:i + 1], tol)[:-1] + simplify(pts[i:], tol)
    return [pts[0], pts[-1]]


result = {}

# --- Saudi border ------------------------------------------------------------
border = None
for rd, pts in read_parts(os.path.join(D, "shp/ne_10m_admin_0_countries.shp"),
                          lambda r: r["ADMIN"] == "Saudi Arabia"):
    if border is None or len(pts) > len(border):
        border = pts
border = simplify([tuple(p) for p in border], 0.01)
# start at the NW corner (Gulf of Aqaba) and draw both ways round
start = min(range(len(border)), key=lambda i: bu_dist(border[i], (34.95, 29.35)))
ring = border[start:-1] + border[:start + 1]
dense = resample(ring, STEP)
cum = [0.0]
for a, b in zip(dense[:-1], dense[1:]):
    cum.append(cum[-1] + bu_dist(a, b))
total = cum[-1]
pts = []
for (lon, lat), c in zip(dense, cum):
    x, y = project(lon, lat)
    pts.append([round(x, 4), round(y, 4), round(max(zmax(lon, lat), 0) + LIFT + 0.01, 4),
                round(min(c, total - c), 4)])
result["saudi_border"] = {"lines": [pts], "max_dist": total / 2}

# Saudi raster mask for clipping internal network
mask_img = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask_img).polygon([px(*p) for p in border], fill=255)
SAUDI = np.asarray(mask_img) > 0


def in_saudi(lon, lat):
    x, y = px(lon, lat)
    x, y = int(x), int(y)
    return 0 <= x < W and 0 <= y < H and SAUDI[y, x]


def clip(polylines, keep):
    """Split polylines keeping only runs of points where keep(p) is True."""
    out = []
    for pl in polylines:
        run = []
        for p in pl:
            if keep(*p):
                run.append(p)
            else:
                if len(run) > 1:
                    out.append(run)
                run = []
        if len(run) > 1:
            out.append(run)
    return out


# --- Saudi internal network (roads + rail) -----------------------------------
raw = []
for rd, pts in read_parts(os.path.join(D, "shp/ne_10m_roads.shp"),
                          lambda r: r["scalerank"] <= 7):
    raw.append([tuple(p) for p in pts])
for rd, pts in read_parts(os.path.join(D, "shp/ne_10m_railroads.shp")):
    raw.append([tuple(p) for p in pts])
sa = clip([resample(pl, 0.05) for pl in raw], lambda lo, la: in_saudi(lo, la))
sa = [simplify(pl, 0.015) for pl in sa]
sa = components(sa, 1.2, snap=1e-2)
fn = network(sa, HUBS["riyadh"])
lines = emit(sa, fn, lift=LIFT)
result["saudi_network"] = {"lines": lines,
                           "max_dist": max(p[3] for l in lines for p in l)}

# --- Regional / global network --------------------------------------------------
raw = []
for rd, pts in read_parts(os.path.join(D, "shp/ne_10m_roads.shp"),
                          lambda r: r["scalerank"] <= 5 and r["type"] in ("Major Highway", "Secondary Highway")):
    raw.append([tuple(p) for p in pts])
for rd, pts in read_parts(os.path.join(D, "shp/ne_10m_railroads.shp"),
                          lambda r: r["scalerank"] <= 4):
    raw.append([tuple(p) for p in pts])
gl = clip([resample(pl, 0.1) for pl in raw],
          lambda lo, la: inside(lo, la, 3) and not in_saudi(lo, la))
gl = [simplify(pl, 0.04) for pl in gl]
gl = components(gl, 5.0)
fn = network(gl, HUBS["riyadh"], virtual_cost=1.15, snap=2e-2)
lines = emit(gl, fn, lift=LIFT)
result["global_network"] = {"lines": lines,
                            "max_dist": max(p[3] for l in lines for p in l)}

# --- Sea lanes ------------------------------------------------------------------
LANES = {
    "suez_europe": [(38.9, 21.4), (38.3, 21.9), (37.3, 23.6), (36.0, 25.6), (34.8, 27.2), (33.8, 27.9), (32.9, 29.0),
                    (32.56, 29.85), (32.33, 31.35), (30.0, 32.4), (25.0, 33.7), (18.5, 35.0),
                    (12.5, 37.6), (5.0, 37.6), (-1.0, 36.4), (-5.6, 35.95), (-9.8, 36.6),
                    (-10.2, 40.5), (-9.6, 44.5), (-6.5, 48.6), (-3.5, 49.9), (-0.5, 50.4), (2.6, 51.4)],
    "asia": [(38.9, 21.4), (38.6, 20.8), (40.0, 18.6), (41.9, 15.2), (43.3, 12.7), (45.5, 12.1),
             (49.5, 12.4), (53.0, 12.8), (58.0, 13.0), (65.0, 11.0), (72.0, 7.8),
             (77.5, 5.4), (81.5, 5.6), (88.0, 5.9), (94.8, 6.5), (97.5, 6.0),
             (99.0, 4.5), (100.5, 3.0), (102.5, 1.8), (103.8, 1.15), (104.6, 1.7),
             (106.5, 4.0), (109.0, 7.0), (111.0, 9.0)],
    "gulf_india": [(50.25, 26.7), (51.8, 26.9), (54.5, 26.4), (56.4, 26.55), (57.2, 25.2),
                   (58.8, 23.6), (61.5, 21.5), (66.0, 19.2), (72.6, 18.8)],
    "africa": [(45.5, 12.1), (49.5, 12.3), (52.3, 12.2), (53.0, 9.5), (49.5, 3.5), (44.0, -1.5),
               (41.2, -6.5), (42.5, -13.0), (39.5, -19.5), (35.8, -24.5), (33.2, -29.0),
               (28.0, -34.8), (20.0, -36.2), (16.6, -33.0), (13.3, -25.0), (10.8, -15.0),
               (7.5, -4.0), (4.5, 3.0), (0.0, 4.0), (-8.0, 3.2), (-13.0, 5.5), (-16.5, 8.5), (-19.0, 12.5), (-19.5, 15.5)],
}
LANE_ORIGIN_D = {"suez_europe": 0.0, "asia": 0.0, "gulf_india": 1.5, "africa": 9.0}
lane_lines = []
for name, wp in LANES.items():
    pl = chaikin(push_to_sea(resample(chaikin(wp, 3), 0.2)), 2)
    pl = chaikin(push_to_sea(pl, 0.3), 1)
    dense = resample(pl, STEP)
    hits = sum(1 for p in dense if is_land(*p))
    if hits:
        print(f"  lane {name}: {hits}/{len(dense)} pts on land")
    d0 = LANE_ORIGIN_D[name]
    cum = [d0]
    for a, b in zip(dense[:-1], dense[1:]):
        cum.append(cum[-1] + bu_dist(a, b))
    pts = []
    for (lon, lat), c in zip(dense, cum):
        x, y = project(lon, lat)
        pts.append([round(x, 4), round(y, 4), 0.03, round(c, 4)])
    lane_lines.append(pts)
result["sea_lanes"] = {"lines": lane_lines,
                       "max_dist": max(p[3] for l in lane_lines for p in l)}

# Ship route: Gulf of Aden -> Bab-el-Mandeb -> Red Sea (reverse of asia lane start)
ship_wp = [(52.5, 12.7), (49.5, 12.4), (45.5, 12.1), (43.3, 12.7), (41.9, 15.2), (40.0, 18.6), (38.6, 20.8)]
pl = chaikin(push_to_sea(resample(chaikin(ship_wp, 3), 0.2)), 2)
result["ship_route"] = {"lines": [[list(project(lo, la)) + [0.0, 0.0] for lo, la in resample(pl, STEP)]],
                        "max_dist": 0}

result["hubs"] = {k: list(project(*v)) + [max(zmax(*v), 0) + LIFT] for k, v in HUBS.items()}

json.dump(result, open(os.path.join(D, "lines.json"), "w"))
for k, v in result.items():
    if k != "hubs":
        print(k, len(v["lines"]), "lines", sum(len(l) for l in v["lines"]), "pts",
              "max_dist", round(v["max_dist"], 2))
