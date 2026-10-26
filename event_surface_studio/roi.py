"""Interactive, browser-native region-of-interest selector for Streamlit >=1.52.

The selection is always expressed in *original video pixels*, regardless of
how wide the browser displays the preview image.
"""

from __future__ import annotations

import math
from pathlib import Path


def normalize_roi(value: object, width: int, height: int) -> tuple[int, int, int, int]:
    """Validate and clamp a browser rectangle to source-video pixel bounds."""
    if width < 1 or height < 1:
        raise ValueError("Video dimensions must be positive")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("ROI must have x, y, width and height")
    try:
        coords = [float(item) for item in value]
    except (ValueError, TypeError) as exc:
        raise ValueError("ROI coordinates must be numeric") from exc
    if not all(math.isfinite(c) for c in coords):
        raise ValueError("ROI coordinates must be finite")
    x, y, w, h = (round(c) for c in coords)
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(1, min(width - x, w))
    h = max(1, min(height - y, h))
    return int(x), int(y), int(w), int(h)


def register_roi_selector():
    """Register once per process; assets are trusted source shipped with this app."""
    import streamlit as st

    assets = Path(__file__).parent / "roi_assets"
    return st.components.v2.component(
        "event_surface_studio_roi_picker",
        html=(assets / "roi.html").read_text(encoding="utf-8"),
        css=(assets / "roi.css").read_text(encoding="utf-8"),
        js=(assets / "roi.js").read_text(encoding="utf-8"),
    )
