"""Cut the GPLC / PIF logos out of the original video's end card so the
recreation uses them exactly as they appear in the source.

Usage: python3 extract_logos.py <video> <out_dir>
Outputs (RGBA PNG, 2x upscaled for crisper edges):
  pif_emblem.png      - PIF roundel, circular alpha
  gplc_dark.png       - GPLC wordmark + chevrons (navy) + star (red)
  gplc_white.png      - same, letters/chevrons white (for dark backgrounds)
  colors.json         - sampled brand colours
"""
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

VIDEO, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
frame = os.path.join(OUT, "_endframe.png")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "24.5", "-i", VIDEO,
                "-frames:v", "1", frame], check=True)
img = np.asarray(Image.open(frame).convert("RGB")).astype(np.float32) / 255.0
UP = 2


def save(arr, name):
    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA")
    im = im.resize((im.width * UP, im.height * UP), Image.LANCZOS)
    im.save(os.path.join(OUT, name))


# --- PIF emblem: bbox x 99..295, y 858..1053 -------------------------------
x0, y0, x1, y1 = 94, 853, 301, 1059
crop = img[y0:y1, x0:x1]
h, w = crop.shape[:2]
cx, cy = 197.0 - x0, 955.5 - y0
r = 98.5
yy, xx = np.mgrid[0:h, 0:w]
d = np.sqrt((xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2)
alpha = np.clip(r - d + 0.5, 0, 1)
save(np.dstack([crop, alpha]), "pif_emblem.png")

# --- GPLC wordmark: x ~405..985, y ~900..1020 ------------------------------
x0, y0, x1, y1 = 400, 895, 990, 1025
crop = img[y0:y1, x0:x1]
lum = crop.mean(2)
bg = np.percentile(lum, 95)
ink_mask = (lum < 0.3)
ink = crop[ink_mask].mean(0)
redness = crop[..., 0] - crop[..., 1]
red_mask = redness > 0.45
red = crop[red_mask].mean(0)

a_ink = np.clip((bg - lum) / (bg - ink.mean()), 0, 1)
a_red = np.clip(redness / (red[0] - red[1]), 0, 1)
is_red = a_red > 0.05
alpha = np.where(is_red, np.maximum(a_red, 0), a_ink)
rgb = np.where(is_red[..., None], red[None, None, :], ink[None, None, :])
save(np.dstack([rgb, alpha]), "gplc_dark.png")
white = np.where(is_red[..., None], red[None, None, :], np.ones(3)[None, None, :])
save(np.dstack([white, alpha]), "gplc_white.png")

# Divider + tagline colours
gold = img[900:1000, 350:356].reshape(-1, 3)
gold = gold[gold.sum(1).argmin()]
green = img[1626:1661, 350:729].reshape(-1, 3)
green = green[green.sum(1).argmin()]
json.dump({"ink": ink.tolist(), "red": red.tolist(), "gold": gold.tolist(),
           "green": green.tolist(), "wordmark_px": [x1 - x0, y1 - y0],
           "emblem_px": [207, 206]},
          open(os.path.join(OUT, "colors.json"), "w"), indent=1)
os.remove(frame)
print("logos ok", ink, red, gold, green)

# --- Split wordmark into glyph clusters (G, P, L, C, chevrons, star) -------------
wm = Image.open(os.path.join(OUT, "gplc_white.png"))
A = np.asarray(wm)[..., 3] > 20
cols = np.nonzero(A.any(0))[0]
clusters, s, p = [], cols[0], cols[0]
for c in cols[1:]:
    if c > p + 6:
        clusters.append((s, p))
        s = c
    p = c
clusters.append((s, p))
print("glyph clusters", clusters)
chev, star = clusters[-2], clusters[-1]
for name, (c0, c1) in (("chevron", chev), ("star", star)):
    for variant in ("white", "dark"):
        im = Image.open(os.path.join(OUT, f"gplc_{variant}.png"))
        sub = np.asarray(im)[:, c0 - 2:c1 + 3]
        rows = np.nonzero(sub[..., 3].max(1) > 20)[0]
        Image.fromarray(sub[max(rows[0] - 2, 0):rows[-1] + 3]).save(
            os.path.join(OUT, f"{name}_{variant}.png"))
