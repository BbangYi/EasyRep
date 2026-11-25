#!/usr/bin/env python3
"""Rasterize the existing EasyRep app icon and wordmark for the opener clip."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


if len(sys.argv) != 3:
    raise SystemExit("usage: render-forest-brand-card.py ICON.webp OUTPUT.png")

icon_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

card = Image.new("RGBA", (480, 160), "#f4f0df")
draw = ImageDraw.Draw(card)
draw.rounded_rectangle((1, 1, 478, 158), radius=7, outline="#e0dfcf", width=2)

icon = Image.open(icon_path).convert("RGBA")
icon.thumbnail((64, 64), Image.Resampling.LANCZOS)
card.alpha_composite(icon, (42, (160 - icon.height) // 2))

font = ImageFont.truetype(font_path, 54)
draw.text((128, 80), "EasyRep", font=font, fill="#183126", anchor="lm")
card.save(output_path)
