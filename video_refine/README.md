# Video refine (Blender compositor)

Refines a finished video in Blender 5.x without touching its content: everything
runs as a compositor node group over the source movie clip.

1. Denoise (OIDN) at source size, mixed 55 % with the original to keep texture
2. Bicubic upscale to `--size` (default 1080x1920)
3. Diamond sharpen (0.22)
4. ASC-CDL grade (power 1.12, slope 1.06, cool shadows) + saturation 1.12
5. Bloom (threshold 0.55, strength 0.45) on route lines, city dots and atmosphere
6. Soft blurred-ellipse vignette (edges at 72 %)

Audio is carried over with a VSE sound strip; output is H.264 + AAC.

```bash
blender -b --factory-startup -P refine.py -- in.mp4 out.mp4
blender -b --factory-startup -P refine.py -- in.mp4 still.png --still 100   # preview one frame
# or with the `bpy` wheel:  python refine.py in.mp4 out.mp4
```

The empty 3D scene is rendered by a 1-sample CPU Cycles pass, so it works headless
without a GPU. A 20 s 480x854 clip takes about 5 minutes on 4 CPU cores.
