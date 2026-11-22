# Globe routes (Blender)

Rebuild of the 9:16 globe "trade routes" film with clean white route lines, solid
node dots that pop once (no pulsing), and a faster camera with a clearer structure:

| frames (24 fps) | shot |
|---|---|
| 1-36    | fade up on the globe from space |
| 36-72   | fast dive onto Riyadh |
| 72-140  | Saudi network draws: Jeddah, Dammam, NEOM, Jizan, Kuwait |
| 140-238 | pull back: Red Sea, Suez, Hormuz, Arabian Sea lanes |
| 238-334 | Africa: coastal lanes, Nile, Sahel and rail corridors |
| 334-430 | swing east: India, Malacca, South-East Asia, Australia |
| 430-480 | pull out on the whole network |

```bash
DATA=/path/to/data
python prep/build_earth.py $DATA          # numpy scipy pillow pyshp; ~1.7k elevation tiles + Natural Earth
blender -b --factory-startup -P build_globe.py -- $DATA out.mp4
blender -b --factory-startup -P build_globe.py -- $DATA test_####.png --still 120,300 --pct 50
blender -b --factory-startup -P build_globe.py -- $DATA frames/ --samples 12   # resumable PNG sequence
```

- `routes.py`: cities, route waypoints, draw-on timing and camera keys. Retime or re-route here.
- `build_globe.py`: scene, camera rig (orbit / heading / tilt), routes, nodes, render + compositor.
- `prep/build_earth.py`: equirectangular colour map from AWS Terrarium elevation and Natural Earth.

All surfaces are emission-shaded, so frames have no sampling noise and don't flicker.
Line and node sizes are driven by camera distance, so they keep one on-screen width.
Full HD takes about 12 s a frame on 4 CPU cores (Cycles, 12 samples).
