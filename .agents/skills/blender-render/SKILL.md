---
name: blender-render
description: Render a Blender scene headless (no UI) from the command line — preview stills, chunked animation renders and the final MP4 — for the gplc_map project or any .blend file. Use when asked to render, preview a frame, check a camera/timing change, or produce the video.
---

# Headless Blender render

Status: written from the project's scripts; **not yet run end to end in a cloud session**
(no Blender binary or GPU there). Note anything that differs when you first run it, and fix this file.

## 0. Find Blender

Use a release binary, not a source build of this repo (a build takes hours).

```bash
B=${BLENDER:-$(command -v blender)}      # e.g. ~/blender-5.2.5-linux-x64/blender
"$B" --version                           # gplc_map targets Blender 5.2
```

If none is installed, ask the user before downloading one
(`https://download.blender.org/release/Blender5.2/blender-5.2.x-linux-x64.tar.xz`, ~350 MB).

EEVEE needs a GPU (OpenGL/Vulkan). On a machine without one it may fail to create a context or
be very slow on a software renderer — say so rather than guess; use the user's machine for real renders.

## 1. Generic .blend file

```bash
"$B" -b file.blend -S <Scene> -f 1                     # one frame (output path from the file)
"$B" -b file.blend -S <Scene> -o /out/frame_#### -F PNG -f 120
"$B" -b file.blend -S <Scene> -s 1 -e 60 -a            # frame range
"$B" -b file.blend --python-expr "import bpy;print(bpy.data.scenes.keys())"
```

Order matters: options apply to renders that come *after* them on the command line
(`-o`, `-F`, `-S` before `-f`/`-a`). Always `-b` (background).

## 2. gplc_map project (`gplc_map/`)

Inputs not in git: `$DATA` (elevation, Natural Earth shapefiles, fonts, logos — see
`gplc_map/README.md` › Pipeline for the `prep/` steps). Output goes to `$OUT`; never commit renders
(PNGs would go to LFS, which this fork rejects).

```bash
cd gplc_map
# Build the .blend (Map, UI, Edit scenes). 3rd arg = resolution %: 50 → 540x960 preview, 100 → 1080x1920.
"$B" -b --factory-startup -P build_scene.py -- "$DATA" "$OUT" 50

# Review stills: scene name, out dir, frame numbers (30 fps; cues live in timeline.py)
"$B" -b "$OUT/gplc_on_the_map.blend" -P render_stills.py -- Map "$OUT/stills" 1 120 300 600
"$B" -b "$OUT/gplc_on_the_map.blend" -P render_stills.py -- UI  "$OUT/stills" 60 700

# Full video: Map + UI layers in 60-frame chunks, then H.264 encode in the Edit scene
./render_all.sh "$B" "$OUT/gplc_on_the_map.blend"      # → $OUT/gplc_on_the_map.mp4
```

Workflow for a change:
1. Edit `timeline.py` (timing, camera keys, title cues) or `build_scene.py` (look, materials).
2. Rebuild the .blend at 50 %, render stills at the affected frames, compare with the previous stills.
3. Only render the full video when the stills look right. Final quality: rebuild at 100.

Look at stills with the Read tool and describe what changed; send the user the key frames.

## Troubleshooting

- `Error: Unable to open a display` / GPU context errors → no usable GPU; render on the user's machine.
- Long full renders: run `render_all.sh` in the background and keep each shell call under 10 minutes;
  the chunked script can be resumed by re-running a scene's frame range.
- Missing `colors.json`, `lines.json`, `tex/*.png` → a `prep/` step was skipped.
- `frame_end` values come from `T["map_end"]` / `T["end"]` in `timeline.py`.
