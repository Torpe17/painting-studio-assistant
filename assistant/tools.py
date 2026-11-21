"""Tool registry: JSON schema (for the model) + Python function (for execution).

Tools always work on the current image (ToolContext) – the model never sends
image data, only parameters. Every return value is compact JSON.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from PIL import Image

from . import image_tools, museum


@dataclass
class ToolContext:
    image: Image.Image
    artifacts: dict[str, Any] = field(default_factory=dict)  # for the UI: images, raw results
    museum_results: dict[str, dict] = field(default_factory=dict)  # id -> artwork (for validation)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[[ToolContext, dict], dict]

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _int_arg(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(args.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _palette(ctx: ToolContext, args: dict) -> dict:
    res = image_tools.extract_palette(ctx.image, _int_arg(args, "num_colors", 6, 3, 10))
    ctx.artifacts["palette"] = res
    return res


def _values(ctx: ToolContext, args: dict) -> dict:
    stats, study = image_tools.value_study(ctx.image, _int_arg(args, "levels", 5, 3, 7))
    ctx.artifacts["value_stats"] = stats
    ctx.artifacts["value_image"] = study
    return stats


def _composition(ctx: ToolContext, args: dict) -> dict:
    stats, overlay = image_tools.composition_analysis(ctx.image)
    ctx.artifacts["composition"] = stats
    ctx.artifacts["composition_image"] = overlay
    # The UI keeps the full numbers; the model gets the worded positions only. Small models otherwise
    # quote raw coordinates ("[0.48, 0.54]") to the painter or misread their direction.
    raw = {"visual_center_of_mass", "strongest_detail_area", "nearest_thirds_point"}
    return {k: v for k, v in stats.items() if k not in raw}


def _museum(ctx: ToolContext, args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "Empty search query."}
    works = museum.search_museums(query, _int_arg(args, "max_results", 4, 1, 6))
    for w in works:
        ctx.museum_results[w["id"]] = w
    ctx.artifacts.setdefault("museum_queries", []).append(query)
    # the model gets no images of the results, only metadata
    return {"query": query, "results": [{k: w[k] for k in ("id", "title", "artist", "date", "medium", "source")}
                                        for w in works]}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool(
        "analyze_palette",
        "Measures the painting's dominant colors with k-means clustering: hex code, share %, color name, "
        "warm/cool classification, mean saturation. Use it before making any claim about color.",
        {"type": "object", "properties": {
            "num_colors": {"type": "integer", "description": "Number of colors to extract (3–10).", "minimum": 3, "maximum": 10},
        }},
        _palette,
    ),
    Tool(
        "analyze_values",
        "Value study (tonal analysis): the image's lightness distribution as dark/mid/light shares, "
        "contrast, value key (high-key/low-key). Use it to assess the light-and-shadow structure.",
        {"type": "object", "properties": {
            "levels": {"type": "integer", "description": "Number of value levels for posterization (3–7).", "minimum": 3, "maximum": 7},
        }},
        _values,
    ),
    Tool(
        "analyze_composition",
        "Measures composition: visual center of mass, location of the most detailed area, distance from the "
        "rule-of-thirds points, left-right and top-bottom weight distribution. Positions are given in words "
        "(e.g. 'bottom right').",
        {"type": "object", "properties": {}},
        _composition,
    ),
    Tool(
        "search_museum",
        "Searches public-domain paintings in the collections of The Met and the Art Institute of Chicago. "
        "Give English keywords (e.g. 'night sky landscape', 'Monet water lilies'). "
        "Only artworks returned here may be recommended.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query in English (subject, style, painter)."},
            "max_results": {"type": "integer", "description": "Number of results (1–6).", "minimum": 1, "maximum": 6},
        }, "required": ["query"]},
        _museum,
    ),
]}


def run_tool(ctx: ToolContext, name: str, args: dict, allowed: set[str]) -> tuple[dict, float]:
    """Runs a tool with a permission check (least privilege). Returns errors as JSON."""
    start = time.perf_counter()
    if name not in allowed or name not in TOOLS:
        result = {"error": f"The tool '{name}' is not allowed in this skill."}
    else:
        try:
            result = TOOLS[name].func(ctx, args or {})
        except Exception as exc:  # noqa: BLE001 – let the model see the error instead of crashing
            result = {"error": f"{type(exc).__name__}: {exc}"}
    return result, time.perf_counter() - start
