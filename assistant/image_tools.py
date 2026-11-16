"""Classical (non-AI) image analysis tools.

They give deterministic, measurable results – the LLM relies on them,
so numerical claims (color, value, balance) cannot be hallucinated.
"""
from __future__ import annotations

import colorsys
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from sklearn.cluster import KMeans

MAX_SIDE = 1024          # larger images are downscaled (cost, speed)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MIN_SIDE = 64
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(ValueError):
    """Invalid uploaded image."""


@dataclass
class PreparedImage:
    image: Image.Image   # RGB, downscaled
    jpeg_bytes: bytes    # re-encoded without EXIF/metadata – this is what the model gets
    original_format: str
    original_size: tuple[int, int]


def prepare_image(data: bytes) -> PreparedImage:
    """Input validation + normalization (size, format, metadata removal)."""
    if not data:
        raise ImageValidationError("Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageValidationError("The image is larger than 15 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ImageValidationError("The file cannot be read as an image.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageValidationError(f"Unsupported format: {fmt}. Only JPEG, PNG, WEBP.")
    if min(img.size) < MIN_SIDE:
        raise ImageValidationError("The image is too small (at least 64 px is needed).")
    original_size = img.size
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)  # new file: GPS/EXIF data is not carried over
    return PreparedImage(img, buf.getvalue(), fmt, original_size)


# ---------------------------------------------------------------- color palette

_HUES = [  # (upper limit in degrees, name)
    (15, "red"), (40, "orange"), (65, "yellow"), (85, "yellow-green"), (150, "green"),
    (185, "turquoise"), (205, "cyan"), (250, "blue"), (275, "violet"), (300, "purple"),
    (335, "magenta"), (360, "red"),
]


def color_name(rgb: tuple[int, int, int]) -> str:
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if l < 0.12:
        return "black"
    if l > 0.92 and s < 0.3:
        return "white"
    if s < 0.12:
        return "dark gray" if l < 0.4 else ("light gray" if l > 0.7 else "gray")
    hue = next(name for limit, name in _HUES if h * 360 <= limit)
    if hue in ("orange", "red") and l < 0.35 and s < 0.6:
        hue = "brown"
    mods = []
    if l < 0.3:
        mods.append("dark")
    elif l > 0.75:
        mods.append("light")
    if s < 0.3:
        mods.append("muted")
    return " ".join(mods + [hue])


def _temperature(rgb) -> str:
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    if s < 0.12:
        return "neutral"
    deg = h * 360
    return "warm" if deg < 75 or deg > 330 else "cool"


def _luminance(arr: np.ndarray) -> np.ndarray:
    """Relative luminance on a 0–100 scale (Rec. 709 weights)."""
    return (0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]) / 255 * 100


def extract_palette(img: Image.Image, num_colors: int = 6) -> dict:
    num_colors = int(np.clip(num_colors, 3, 10))
    small = img.copy()
    small.thumbnail((200, 200))
    pixels = np.asarray(small, dtype=np.float32).reshape(-1, 3)
    km = KMeans(n_clusters=num_colors, n_init=4, random_state=0).fit(pixels)
    counts = np.bincount(km.labels_, minlength=num_colors)
    order = np.argsort(-counts)
    colors = []
    temps = {"warm": 0.0, "cool": 0.0, "neutral": 0.0}
    sats = []
    for idx in order:
        rgb = tuple(int(round(c)) for c in km.cluster_centers_[idx])
        share = counts[idx] / counts.sum()
        temp = _temperature(rgb)
        temps[temp] += share
        _, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        sats.append(s * share)
        colors.append({
            "hex": "#%02x%02x%02x" % rgb,
            "rgb": list(rgb),
            "share_percent": round(share * 100, 1),
            "name": color_name(rgb),
            "temperature": temp,
            "lightness": round(l * 100),
        })
    return {
        "colors": colors,
        "temperature_balance_percent": {k: round(float(v) * 100, 1) for k, v in temps.items()},
        "mean_saturation_percent": round(float(sum(sats)) * 100, 1),
    }


# ---------------------------------------------------------------- value (tonal value)

def value_study(img: Image.Image, levels: int = 5) -> tuple[dict, Image.Image]:
    """Grayscale, posterized value study + statistics."""
    levels = int(np.clip(levels, 3, 7))
    arr = np.asarray(img, dtype=np.float32)
    lum = _luminance(arr)
    bands = np.minimum((lum / 100 * levels).astype(int), levels - 1)
    shades = np.linspace(20, 235, levels).astype(np.uint8)
    study = Image.fromarray(shades[bands], mode="L")

    dark = float((lum < 33).mean())
    light = float((lum > 66).mean())
    mid = 1 - dark - light
    p5, p95 = np.percentile(lum, [5, 95])
    mean = float(lum.mean())
    key = "light (high-key)" if mean > 60 else ("dark (low-key)" if mean < 35 else "middle (mid-key)")
    band_share = np.bincount(bands.ravel(), minlength=levels) / bands.size
    stats = {
        "levels": levels,
        "value_key": key,
        "mean_value": round(mean, 1),
        "value_range_p5_p95": [round(float(p5), 1), round(float(p95), 1)],
        "contrast_std": round(float(lum.std()), 1),
        "dark_mid_light_percent": [round(dark * 100, 1), round(mid * 100, 1), round(light * 100, 1)],
        "band_share_percent": [round(float(x) * 100, 1) for x in band_share],
    }
    return stats, study


# ---------------------------------------------------------------- composition

def position_label(x: float, y: float) -> str:
    """Coordinates in words (3x3 grid), so the model does not have to interpret the y-axis direction."""
    row = "top" if y < 1 / 3 else ("bottom" if y > 2 / 3 else "middle")
    col = "left" if x < 1 / 3 else ("right" if x > 2 / 3 else "center")
    if row == "middle" and col == "center":
        return "center"
    return f"{row} {col}" if row != "middle" else f"middle {col}"


def composition_analysis(img: Image.Image) -> tuple[dict, Image.Image]:
    """Visual center of mass (edge strength + local contrast) and rule-of-thirds grid."""
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    gy, gx = np.gradient(gray)
    weight = np.hypot(gx, gy)
    weight = weight / (weight.sum() + 1e-9)
    h, w = gray.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = float((weight * xs).sum() / w), float((weight * ys).sum() / h)

    # strongest detail cluster: heaviest cell of an 8x8 grid
    grid = 8
    cell = weight[: h - h % grid, : w - w % grid].reshape(grid, h // grid, grid, w // grid).sum(axis=(1, 3))
    gyx = np.unravel_index(np.argmax(cell), cell.shape)
    hot = (float((gyx[1] + 0.5) / grid), float((gyx[0] + 0.5) / grid))

    thirds = [(x, y) for x in (1 / 3, 2 / 3) for y in (1 / 3, 2 / 3)]
    nearest = min(thirds, key=lambda p: (p[0] - hot[0]) ** 2 + (p[1] - hot[1]) ** 2)
    dist = float(np.hypot(nearest[0] - hot[0], nearest[1] - hot[1]))

    left = float(weight[:, : w // 2].sum())
    top = float(weight[: h // 2, :].sum())
    stats = {
        "aspect_ratio": round(w / h, 2),
        "orientation": "landscape" if w > h * 1.05 else ("portrait" if h > w * 1.05 else "square"),
        "visual_center_of_mass": [round(cx, 2), round(cy, 2)],
        "visual_center_of_mass_position": position_label(cx, cy),
        "strongest_detail_area": [round(hot[0], 2), round(hot[1], 2)],
        "strongest_detail_area_position": position_label(hot[0], hot[1]),
        "nearest_thirds_point": [round(nearest[0], 2), round(nearest[1], 2)],
        "distance_to_thirds_point": round(dist, 3),
        "on_thirds_point": bool(dist < 0.12),
        "detail_in_center": bool(abs(hot[0] - 0.5) < 0.12 and abs(hot[1] - 0.5) < 0.12),
        "left_right_weight_percent": [round(left * 100, 1), round((1 - left) * 100, 1)],
        "top_bottom_weight_percent": [round(top * 100, 1), round((1 - top) * 100, 1)],
        "visual_weight_percent": {  # same numbers, labelled, so the model cannot mix up the order
            "left": round(left * 100, 1), "right": round((1 - left) * 100, 1),
            "top": round(top * 100, 1), "bottom": round((1 - top) * 100, 1),
        },
        "note": "Coordinates are between 0 and 1 (top-left corner = 0,0; y grows downward). Use the *_position fields for wording. Measured edge strength, not meaning.",
    }

    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    lw = max(2, w // 300)
    for t in (1 / 3, 2 / 3):
        draw.line([(w * t, 0), (w * t, h)], fill=(255, 255, 255), width=lw)
        draw.line([(0, h * t), (w, h * t)], fill=(255, 255, 255), width=lw)
    r = max(8, w // 60)
    hx, hy = hot[0] * w, hot[1] * h
    draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=(255, 60, 60), width=lw + 1)
    mx, my = cx * w, cy * h
    draw.line([(mx - r, my), (mx + r, my)], fill=(60, 200, 255), width=lw + 1)
    draw.line([(mx, my - r), (mx, my + r)], fill=(60, 200, 255), width=lw + 1)
    return stats, overlay
