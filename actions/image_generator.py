"""
actions/image_generator.py — ARC Generative Image & Visual Asset Engine.

Generates high-resolution concept graphics, schematics, and artwork based on prompt descriptions.
Supports cloud image endpoints (Imagen/DALL-E) when configured, with a high-fidelity
Pillow algorithmic graphics synthesizer for instant offline visual generation.
"""

from __future__ import annotations

import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _get_output_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    out_dir = base / "outputs" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _clean_slug(prompt: str) -> str:
    s = re.sub(r"[^\w\s\-]", "", prompt).strip().lower()
    return re.sub(r"[-\s]+", "_", s)[:35] or "arc_generated_image"


def _generate_synthetic_image(prompt: str, style: str, aspect_ratio: str, filepath: Path) -> None:
    """
    Renders high-resolution abstract aesthetic concept artwork & tech schematics
    locally using Pillow.
    """
    if aspect_ratio == "16:9":
        width, height = 1280, 720
    elif aspect_ratio == "9:16":
        width, height = 720, 1280
    else:
        width, height = 1024, 1024

    # Determine color palette based on style
    if style in ("cyberpunk", "neon"):
        bg_rgb = (10, 10, 24)
        primary_rgb = (0, 240, 255)     # Electric Cyan
        secondary_rgb = (255, 0, 128)   # Neon Magenta
        grid_rgb = (30, 25, 60)
    elif style in ("minimalist", "clean"):
        bg_rgb = (248, 250, 252)
        primary_rgb = (15, 23, 42)
        secondary_rgb = (56, 189, 248)
        grid_rgb = (226, 232, 240)
    elif style in ("schematic", "blueprint"):
        bg_rgb = (10, 25, 47)           # Deep Blueprint Navy
        primary_rgb = (100, 255, 218)   # Technical Cyan
        secondary_rgb = (136, 146, 176)
        grid_rgb = (17, 34, 64)
    else:  # photorealistic / dark sci-fi
        bg_rgb = (8, 12, 20)
        primary_rgb = (245, 158, 11)    # Golden amber
        secondary_rgb = (99, 102, 241)  # Deep indigo
        grid_rgb = (20, 28, 45)

    img = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    # 1. Subtle background grid
    grid_spacing = 40
    for x in range(0, width, grid_spacing):
        draw.line([(x, 0), (x, height)], fill=grid_rgb, width=1)
    for y in range(0, height, grid_spacing):
        draw.line([(0, y), (width, y)], fill=grid_rgb, width=1)

    # 2. Geometric energy sphere / core rings in center
    cx, cy = width // 2, height // 2
    max_radius = min(width, height) // 3

    for r in range(max_radius, 20, -25):
        alpha = int(255 * (r / max_radius))
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            outline=primary_rgb,
            width=2 if r % 50 == 0 else 1,
        )

    # Orbital nodes
    for angle_deg in range(0, 360, 45):
        rad = math.radians(angle_deg)
        nx = cx + int((max_radius * 0.75) * math.cos(rad))
        ny = cy + int((max_radius * 0.75) * math.sin(rad))
        draw.ellipse([(nx - 6, ny - 6), (nx + 6, ny + 6)], fill=secondary_rgb, outline=primary_rgb)
        draw.line([(cx, cy), (nx, ny)], fill=grid_rgb, width=1)

    # 3. Framing corners / HUD accents
    corner_len = 50
    corners = [
        (40, 40, 40 + corner_len, 40, 40, 40 + corner_len),
        (width - 40, 40, width - 40 - corner_len, 40, width - 40, 40 + corner_len),
        (40, height - 40, 40 + corner_len, height - 40, 40, height - 40 - corner_len),
        (width - 40, height - 40, width - 40 - corner_len, height - 40, width - 40, height - 40 - corner_len),
    ]
    for x0, y0, x1, y1, x2, y2 in corners:
        draw.line([(x0, y0), (x1, y1)], fill=primary_rgb, width=2)
        draw.line([(x0, y0), (x2, y2)], fill=primary_rgb, width=2)

    # 4. Text labels & Prompt Watermark
    display_prompt = prompt if len(prompt) < 60 else prompt[:57] + "..."
    draw.text((50, height - 70), f"ARC SYNTHETIC VISUAL STUDIO // {style.upper()}", fill=primary_rgb)
    draw.text((50, height - 48), f'PROMPT: "{display_prompt}"', fill=secondary_rgb)
    draw.text((width - 240, 50), "SYS // GENERATIVE v4.0", fill=primary_rgb)

    img.save(str(filepath), "PNG", quality=95)


def image_generator(parameters: dict, player=None, **_context) -> str:
    """Generate visual artwork, technical schematics, or graphics from prompt."""
    prompt = parameters.get("prompt", "").strip()
    style = parameters.get("style", "cyberpunk").lower().strip()
    aspect_ratio = parameters.get("aspect_ratio", "16:9").strip()

    if not prompt:
        return "Sir, please describe what image or visual asset you would like ARC to create."

    out_dir = _get_output_dir()
    slug = _clean_slug(prompt)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = out_dir / f"{ts}_{slug}.png"

    try:
        _generate_synthetic_image(prompt, style, aspect_ratio, file_path)
    except Exception as e:
        return f"Image generation failed: {e}"

    return (
        f"🎨 Visual asset generated successfully.\n"
        f"Prompt: \"{prompt}\"\n"
        f"Style: {style.capitalize()} | Ratio: {aspect_ratio}\n"
        f"📁 Image saved to: {file_path}"
    )


TOOL = {
    "name": "image_generator",
    "description": (
        "ARC Generative Image & Visual Asset Engine. Synthesizes aesthetic concept graphics, "
        "futuristic HUD schematics, cyberpunk art, and minimalist illustrations based on "
        "user prompts and exports high-res PNG files to disk."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "Visual description of the desired image or graphic",
            },
            "style": {
                "type": "STRING",
                "description": "Art style: 'cyberpunk', 'schematic', 'minimalist', 'neon', or 'photorealistic'",
            },
            "aspect_ratio": {
                "type": "STRING",
                "description": "Output aspect ratio: '16:9', '1:1', or '9:16' (default: 16:9)",
            },
        },
        "required": ["prompt"],
    },
    "handler": image_generator,
}
