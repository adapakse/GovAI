# -*- coding: utf-8 -*-
"""Generuje rastrowe wersje logo GovAI (PNG/ICO) z geometrii zdefiniowanej w SVG."""

import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "raster")
os.makedirs(OUT, exist_ok=True)

TEAL  = (0, 180, 216, 255)
BLUE  = (30, 111, 191, 255)
DARK  = (13, 27, 42, 255)
NAVY  = (27, 53, 94, 255)
LGRAY = (240, 244, 248, 255)
CLEAR = (0, 0, 0, 0)

FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"


def draw_mark(scale, ring_color=TEAL, node_color=LGRAY, bg=None, bg_radius_frac=0.20):
    """Rysuje znak G na kwadratowym płótnie scale x scale (bazując na viewBox 100x100)."""
    img = Image.new("RGBA", (scale, scale), CLEAR)
    d = ImageDraw.Draw(img)
    k = scale / 100.0

    if bg is not None:
        d.rounded_rectangle([0, 0, scale, scale], radius=int(scale * bg_radius_frac), fill=bg)

    cx, cy, r = 50 * k, 50 * k, 30 * k
    sw = 13 * k
    outer = r + sw / 2
    inner = r - sw / 2
    d.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=ring_color)
    d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=CLEAR if bg is None else bg)

    gap = [58 * k, 10 * k, 90 * k, 42 * k]
    d.rectangle(gap, fill=CLEAR if bg is None else bg)

    x1, y1, x2, y2 = 74 * k, 27 * k, 56 * k, 27 * k
    half = sw / 2
    d.line([(x1, y1), (x2, y2)], fill=ring_color, width=int(sw))
    d.ellipse([x1 - half, y1 - half, x1 + half, y1 + half], fill=ring_color)
    d.ellipse([x2 - half, y2 - half, x2 + half, y2 + half], fill=ring_color)

    nr = 8.5 * k
    d.ellipse([x2 - nr, y2 - nr, x2 + nr, y2 + nr], fill=node_color)
    return img


def draw_lockup(scale_h, text_color, accent_color, ring_color, node_color):
    """Pełny logotyp: znak + 'GovAI'. scale_h = wysokość w px (viewBox 100 -> scale_h)."""
    k = scale_h / 100.0
    width = int(340 * k)
    height = scale_h
    canvas = Image.new("RGBA", (width, height), CLEAR)

    mark = draw_mark(scale_h, ring_color=ring_color, node_color=node_color)
    canvas.alpha_composite(mark, (0, 0))

    d = ImageDraw.Draw(canvas)
    font_size = int(46 * k)
    font = ImageFont.truetype(FONT_BOLD, font_size)
    text_x = int(112 * k)
    baseline_y = int(63 * k)
    # PIL pozycjonuje od top-left glifu; korygujemy offsetem ascent
    ascent, descent = font.getmetrics()
    top_y = baseline_y - ascent

    gov = "Gov"
    ai = "AI"
    d.text((text_x, top_y), gov, font=font, fill=text_color)
    gov_w = d.textlength(gov, font=font)
    d.text((text_x + gov_w, top_y), ai, font=font, fill=accent_color)

    return canvas


def save_with_margin(img, path, margin_frac=0.08, bg=None):
    w, h = img.size
    mw, mh = int(w * margin_frac), int(h * margin_frac)
    canvas = Image.new("RGBA", (w + 2 * mw, h + 2 * mh), bg if bg else CLEAR)
    canvas.alpha_composite(img, (mw, mh))
    canvas.save(path)


# ── Znak samodzielny ──────────────────────────────────────────────────────────
mark_dark_bg  = draw_mark(1024, ring_color=TEAL, node_color=LGRAY)
save_with_margin(mark_dark_bg, os.path.join(OUT, "logo-mark.png"))

mark_mono_light = draw_mark(1024, ring_color=LGRAY, node_color=(255, 255, 255, 90))
save_with_margin(mark_mono_light, os.path.join(OUT, "logo-mark-mono-light.png"))

mark_mono_dark = draw_mark(1024, ring_color=DARK, node_color=(13, 27, 42, 90))
save_with_margin(mark_mono_dark, os.path.join(OUT, "logo-mark-mono-dark.png"))

# ── Logotyp pełny ──────────────────────────────────────────────────────────────
lockup_dark = draw_lockup(400, text_color=LGRAY, accent_color=TEAL, ring_color=TEAL, node_color=LGRAY)
save_with_margin(lockup_dark, os.path.join(OUT, "logo-lockup-dark-bg.png"), margin_frac=0.04)

lockup_light = draw_lockup(400, text_color=NAVY, accent_color=BLUE, ring_color=TEAL, node_color=DARK)
save_with_margin(lockup_light, os.path.join(OUT, "logo-lockup-light-bg.png"), margin_frac=0.04)

# ── Favicon (z tłem, kwadrat, wiele rozdzielczości w jednym .ico) ──────────────
fav_master = draw_mark(512, ring_color=TEAL, node_color=LGRAY, bg=DARK, bg_radius_frac=0.20)
fav_master.save(os.path.join(OUT, "favicon-512.png"))

sizes = [16, 24, 32, 48, 64, 128, 256]
fav_images = [fav_master.resize((s, s), Image.LANCZOS) for s in sizes]
fav_images[0].save(
    os.path.join(OUT, "favicon.ico"),
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=fav_images[1:],
)

print("OK — wygenerowano rastrowe wersje logo w", OUT)
