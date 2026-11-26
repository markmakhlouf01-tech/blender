# Blender fork — contributor guide

A personal fork of Blender (C/C++ core, Python UI/add-ons). GitHub is only a mirror of upstream:
patches for Blender itself go to projects.blender.org
(https://developer.blender.org/docs/handbook/contributing/), not PRs here.

The fork's own work lives in **`gplc_map/`** — a procedural Blender 5.2 recreation of the GPLC
"On the map" 9:16 spot. Treat it as a standalone Python project; most tasks here are about it.

## Layout

- `gplc_map/` — `config.py` (map extent, projection, resolution), `timeline.py` (all timing and
  camera keys, 30 fps), `build_scene.py` (builds the `Map`, `UI`, `Edit` scenes),
  `render_stills.py`, `render_all.sh`, `prep/` (data download and texture/line generation).
  Pipeline: `gplc_map/README.md`.
- `source/blender/` — core C/C++ (editors, draw/EEVEE, sequencer, nodes …), `intern/` (Cycles,
  guardedalloc …), `scripts/` — bundled Python (UI, startup, add-ons), `tests/` — gtests and Python
  tests, `build_files/` — CMake and platform build scripts.

## Rendering

Use the `blender-render` skill (`.agents/skills/blender-render`). Short version:

```bash
blender -b --factory-startup -P gplc_map/build_scene.py -- "$DATA" "$OUT" 50
blender -b "$OUT/gplc_on_the_map.blend" -P gplc_map/render_stills.py -- Map "$OUT/stills" 120 300
gplc_map/render_all.sh blender "$OUT/gplc_on_the_map.blend"
```

No GPU is needed for previews: in the "Visual work" cloud environment Blender is installed and EEVEE
renders on the CPU through Mesa (slow but fine for stills). Do full-length finals on the user's GPU machine.

## Rules (gplc_map)

- Retime in `timeline.py` only; don't hard-code frames in `build_scene.py`.
- Never commit data (`$DATA`), renders, `.blend` outputs or videos. PNG/MP4 are tracked by LFS
  in this repo and the fork can't accept LFS pushes. The `.mp4` at the repo root is a reference
  upload; don't add more.
- After a visual change, render stills at the affected frames and look at them before committing.
- Commit messages: one line describing the visible change (e.g. "Ship shot: aim camera lower …").

## Building Blender itself (rarely needed)

Prefer a release binary. A source build takes 30+ minutes and several GB; on Linux:
`make update` (fetches libraries), then `make developer ninja ccache` (or `make lite` for a smaller
build). Tests: `make test`. Format: `make format`. `make help` lists all targets.
Don't start a full build without asking the user first.
