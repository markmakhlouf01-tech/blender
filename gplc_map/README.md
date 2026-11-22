# GPLC "On the map" – Blender recreation

Procedural rebuild of the 9:16 GPLC "On the map" spot in Blender 5.2: a real
elevation/bathymetry relief map, white route lines that draw on from Riyadh
outward with a softly breathing glow, a container ship sailing into the Red Sea,
and a 2D overlay (titles, progress bar, white wipe, end card).

## Pipeline
```bash
DATA=/path/to/data      # downloaded/generated assets (not committed)
OUT=/path/to/out
VIDEO=original.mp4      # the original film; logos are cut from its end card

python3 prep/fetch_elevation.py $DATA 6          # AWS Terrarium tiles -> elevation.npy
# Natural Earth 10m shapefiles unzipped into $DATA/shp/ (countries, lakes, roads,
# railroads, populated_places_simple); Orbitron + Montserrat static TTFs in $DATA/fonts/
python3 prep/build_textures.py $DATA             # colour, normal, lights, heights
python3 prep/build_lines.py $DATA                # route geometry + draw-on distances
python3 prep/extract_logos.py $VIDEO $DATA/logos # PIF emblem + GPLC wordmark

blender -b --factory-startup -P build_scene.py -- $DATA $OUT 50   # 50 = 540x960 preview
./render_all.sh blender $OUT/gplc_on_the_map.blend                 # -> $OUT/gplc_on_the_map.mp4
```

## Files
- `config.py` – map extent and projection, resolution
- `timeline.py` – every timing, camera key, line-reveal and title cue (retime here)
- `build_scene.py` – builds the `Map`, `UI` and `Edit` scenes
- `render_stills.py` – render individual frames for review
- `render_all.sh` – chunked render of both layers, then MP4 encode in the VSE

Set `T["audio"]` in `timeline.py` to a music file to add it in the Edit scene.

## Digital restyle
`digital_refine.py` restyles a finished cut in the compositor only (no 3D):
beat-synced punch-in zooms and shake, RGB split, slice and block glitches,
bloom and star streaks on the route nodes, a cool grade, scanlines, a scan bar,
a scrolling grid, a live HUD (timecode, frame counter, coordinates), grain,
a pixel boot-up intro and a CRT power-off outro. Hit timing is the `HITS` list
at the top of the script.

```bash
./render_digital.sh original.mp4 $OUT blender      # -> $OUT/digital_refine.mp4 (720x1280)
```
It also runs with the `bpy` wheel instead of a Blender install (`pip install bpy`,
then pass that interpreter as the third argument).
