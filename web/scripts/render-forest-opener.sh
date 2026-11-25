#!/usr/bin/env bash
set -euo pipefail

# Renders the existing EasyRep entrance assets as a clean opening clip.
# The last 0.7 seconds dissolve to the deck background so an editor can cut
# directly into the first "서비스의 필요성" slide without capturing browser UI.

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
forest="$project_dir/public/textures/forest-interior.webp"
icon="$project_dir/public/brand/easyrep-app-icon.webp"
output="${1:-$project_dir/../video/easyrep-forest-opener-1080p.mp4}"
brand_renderer="$project_dir/scripts/render-forest-brand-card.py"
brand_png="$(mktemp -t easyrep-forest-brand).png"
trap 'rm -f "$brand_png"' EXIT

command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
test -f "$forest" && test -f "$icon" && test -f "$brand_renderer"
mkdir -p "$(dirname "$output")"
python3 "$brand_renderer" "$icon" "$brand_png"

ffmpeg -y \
  -loop 1 -framerate 30 -i "$forest" \
  -loop 1 -framerate 30 -i "$brand_png" \
  -filter_complex "
    color=c=#eff2e9:s=1920x1080:d=3.2[deck];
    [0:v]scale=2020:1136:force_original_aspect_ratio=increase,crop=1920:1080,
         zoompan=z='max(1,1.025-on*0.000260417)':d=96:s=1920x1080:fps=30,
         format=rgba,fade=t=out:st=2.5:d=0.7:alpha=1[forest];
    color=c=#102519@0.50:s=1920x1080:d=3.2,format=rgba,fade=t=out:st=2.5:d=0.7:alpha=1[shade];
    [forest][shade]overlay=shortest=1[scene];
    [1:v]format=rgba,fade=t=in:st=0.15:d=1:alpha=1,fade=t=out:st=2.5:d=0.7:alpha=1[brand];
    [deck][scene]overlay=shortest=1[base];
    [base][brand]overlay=x=(W-w)/2:y=(H-h)/2,format=yuv420p[out]
  " \
  -map "[out]" -t 3.2 -r 30 -an -movflags +faststart \
  -c:v libx264 -preset slow -crf 18 "$output"

echo "Rendered $output"
