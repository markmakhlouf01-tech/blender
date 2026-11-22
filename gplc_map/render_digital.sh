#!/usr/bin/env bash
# Digital restyle of a finished cut: compositor render, then encode with the source audio.
#   ./render_digital.sh SOURCE.mp4 OUT_DIR [python-with-bpy | blender]
set -euo pipefail
SRC=$1; OUT=$2; RUNNER=${3:-blender}
here=$(cd "$(dirname "$0")" && pwd)
if [[ $RUNNER == *blender ]]; then
  "$RUNNER" -b --factory-startup -P "$here/digital_refine.py" -- "$SRC" "$OUT" 100
else
  "$RUNNER" "$here/digital_refine.py" -- "$SRC" "$OUT" 100
fi
fps=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$SRC")
ffmpeg -y -framerate "$fps" -i "$OUT/frames/%04d.png" -i "$SRC" -map 0:v -map 1:a? \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -movflags +faststart \
  -c:a aac -b:a 192k -shortest "$OUT/digital_refine.mp4"
