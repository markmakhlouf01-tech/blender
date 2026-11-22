#!/usr/bin/env bash
# Render Map + UI layers in chunks (keeps memory flat), then encode via the Edit scene.
# usage: render_all.sh <blender> <blend> [chunk]
set -euo pipefail
B=$1; F=$2; C=${3:-60}
read MAP_END END < <("$B" -b "$F" --python-expr "import bpy;print('RANGE',bpy.data.scenes['Map'].frame_end,bpy.data.scenes['UI'].frame_end)" 2>/dev/null | awk '/^RANGE/{print $2, $3}')
for SC in Map UI; do
  E=$([ $SC = Map ] && echo $MAP_END || echo $END)
  for ((s=1; s<=E; s+=C)); do
    e=$((s+C-1)); ((e>E)) && e=$E
    echo "[$SC] frames $s-$e"
    "$B" -b "$F" -S $SC -s $s -e $e -a 2>&1 | grep -E 'Saved|Error' | tail -1
  done
done
echo "[Edit] encoding"
"$B" -b "$F" -S Edit -a 2>&1 | grep -E 'Saved|Error|Append' | tail -2
