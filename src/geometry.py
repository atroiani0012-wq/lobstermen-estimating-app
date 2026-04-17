"""Vector geometry extraction from CAD-exported PDFs via pdfplumber.

Why: when a PDF was made from a CAD system (Bluebeam, AutoCAD publish,
Civil3D, etc.), every dimension line, tick mark, and symbol is preserved as
vector geometry with exact coordinates. That's ground truth — Claude Vision
has to re-read it from a rasterized image, we can read it directly.

Pipeline:
  extract_page_geometry(page) → raw lines/rects/curves/text as dataclasses
  detect_dimension_lines(lines, text) → pairs of perpendicular ticks + label
  detect_symbol_clusters(lines, rects, curves) → repeated shapes w/ counts
  compute_scale_from_geometry(dimensions) → pixel→inch ratio if consistent
  format_geometry_for_claude(...) → plain-text context block for the prompt
  is_vector_pdf(page) → gate: scanned PDFs return nothing useful here

The module does not own any Anthropic calls; everything here is free and
deterministic. It's meant to run before the vision pipeline so Claude sees
hard numbers first and the image as corroboration.
"""
from __future__ import annotations

import io
import math
import pathlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExtractedLine:
    x0: float
    y0: float
    x1: float
    y1: float
    length_px: float
    orientation: str          # "horizontal" | "vertical" | "diagonal"
    stroke_width: float = 0.0

    @property
    def mid(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass
class ExtractedText:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float = 0.0
    font_name: str = ""

    @property
    def mid(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass
class DimensionLine:
    start: tuple[float, float]
    end: tuple[float, float]
    length_px: float
    orientation: str
    label_text: str
    real_world_value: str | None
    real_world_inches: float | None
    confidence: str   # "high" | "medium" | "low"


@dataclass
class SymbolCluster:
    symbol_type: str
    locations: list[tuple[float, float]] = field(default_factory=list)
    count: int = 0
    bounding_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Raw extraction
# ---------------------------------------------------------------------------

def _orient(dx: float, dy: float, tol: float = 2.0) -> str:
    if abs(dy) < tol and abs(dx) >= tol:
        return "horizontal"
    if abs(dx) < tol and abs(dy) >= tol:
        return "vertical"
    return "diagonal"


def extract_page_geometry(page: Any) -> dict[str, Any]:
    """Pull lines, rectangles, curves, and word-level text off a pdfplumber page.

    `page.lines` items are dicts with keys x0/x1/top/bottom/linewidth etc.;
    `page.extract_words()` returns word-level groupings with bounding boxes.
    Coordinates are in PDF points (1pt = 1/72 inch). We preserve them as-is.
    """
    lines: list[ExtractedLine] = []
    for entry in page.lines:
        x0 = float(entry["x0"])
        x1 = float(entry["x1"])
        y0 = float(entry.get("top", entry.get("y0", 0)))
        y1 = float(entry.get("bottom", entry.get("y1", 0)))
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        orientation = _orient(dx, dy)
        lines.append(ExtractedLine(
            x0=x0, y0=y0, x1=x1, y1=y1,
            length_px=length, orientation=orientation,
            stroke_width=float(entry.get("linewidth") or entry.get("lineWidth") or 0.0),
        ))

    text_objects: list[ExtractedText] = []
    try:
        words = page.extract_words() or []
    except Exception:
        words = []
    for w in words:
        try:
            text_objects.append(ExtractedText(
                text=w["text"],
                x0=float(w["x0"]), y0=float(w["top"]),
                x1=float(w["x1"]), y1=float(w["bottom"]),
                font_size=float(w.get("size") or 0),
                font_name=str(w.get("fontname") or ""),
            ))
        except (KeyError, ValueError, TypeError):
            continue

    return {
        "lines": lines,
        "rects": list(getattr(page, "rects", []) or []),
        "curves": list(getattr(page, "curves", []) or []),
        "text": text_objects,
        "page_width": float(getattr(page, "width", 0) or 0),
        "page_height": float(getattr(page, "height", 0) or 0),
    }


def is_vector_pdf(page: Any) -> bool:
    """Return True when a page has enough vector content to extract from.

    Scanned PDFs register as 0 lines, 0 curves, 0 words (just a single big
    raster image). Those cases get handed off to the vision pipeline.
    """
    try:
        n_lines = len(page.lines)
        n_curves = len(getattr(page, "curves", []) or [])
        n_words = len(page.extract_words() or [])
        n_images = len(getattr(page, "images", []) or [])
    except Exception:
        return False
    if n_lines > 10 or n_curves > 5 or n_words > 20:
        return True
    if n_images and not (n_lines or n_words):
        return False
    return False


# ---------------------------------------------------------------------------
# Dimension text parsing
# ---------------------------------------------------------------------------

_FEET_INCHES_RE = re.compile(r"""
    ^\s*
    (?P<feet>\d+(?:\.\d+)?)
    \s*['\u2032]
    \s*-?\s*
    (?P<inch>\d+(?:\.\d+)?)
    \s*["\u2033]?        # optional closing inches marker
    \s*
""", re.VERBOSE)
_FEET_RE = re.compile(r"^\s*(?P<feet>\d+(?:\.\d+)?)\s*['\u2032]\s*$")
_INCH_RE = re.compile(r"^\s*(?P<inch>\d+(?:\.\d+)?)\s*[\"\u2033]\s*$")
_MM_RE   = re.compile(r"^\s*(?P<v>\d+(?:\.\d+)?)\s*(?:mm)\s*$", re.IGNORECASE)
_M_RE    = re.compile(r"^\s*(?P<v>\d+(?:\.\d+)?)\s*(?:m)\s*$", re.IGNORECASE)


def parse_dimension_text(text: str) -> tuple[str | None, float | None]:
    """Parse '25'-0"', '10.5'', '6" O.C.', '2.5 m', etc. Returns (display, inches).

    Unit-less numbers return (text, None) — the caller must decide what to do
    without a unit hint.
    """
    if not text or not text.strip():
        return None, None
    raw = text.strip()
    # Strip common suffixes that shouldn't affect the numeric value.
    cleaned = re.sub(r"\b(O\.?\s*C\.?|TYP\.?|CLR\.?|MIN\.?|MAX\.?)\b.*$", "", raw, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(",")  # trailing commas are common

    m = _FEET_INCHES_RE.match(cleaned)
    if m:
        inches = float(m.group("feet")) * 12 + float(m.group("inch"))
        return raw, inches
    m = _FEET_RE.match(cleaned)
    if m:
        return raw, float(m.group("feet")) * 12
    m = _INCH_RE.match(cleaned)
    if m:
        return raw, float(m.group("inch"))
    m = _M_RE.match(cleaned)
    if m:
        return raw, float(m.group("v")) * 39.3701  # metres → inches
    m = _MM_RE.match(cleaned)
    if m:
        return raw, float(m.group("v")) / 25.4     # mm → inches
    return raw, None


# ---------------------------------------------------------------------------
# Dimension line detection
# ---------------------------------------------------------------------------

def detect_dimension_lines(
    lines: list[ExtractedLine],
    text_objects: list[ExtractedText],
    tolerance_px: float = 10.0,
    min_main_length: float = 30.0,
    max_tick_length: float = 25.0,
    label_search_px: float = 30.0,
) -> list[DimensionLine]:
    """Identify dimension lines by pairing long rectilinear segments with
    perpendicular "tick" marks at each endpoint and a nearby text label.

    This is deliberately a simple heuristic — it will miss exotic styles
    (e.g., arrowhead dimensions with no ticks, or radial dimensions). It
    catches the dominant convention on structural / civil plans and reports
    confidence when the label match is ambiguous.
    """
    main_lines = [l for l in lines if l.length_px >= min_main_length
                  and l.orientation in ("horizontal", "vertical")]
    tick_lines = [l for l in lines if l.length_px <= max_tick_length]

    # Bucket ticks by orientation for faster lookup.
    horiz_ticks = [t for t in tick_lines if t.orientation == "horizontal"]
    vert_ticks  = [t for t in tick_lines if t.orientation == "vertical"]

    results: list[DimensionLine] = []
    for main in main_lines:
        if main.orientation == "horizontal":
            ticks = vert_ticks
            has_start = any(abs(t.x0 - main.x0) < tolerance_px and abs(t.y0 - main.y0) < tolerance_px * 2 for t in ticks)
            has_end   = any(abs(t.x0 - main.x1) < tolerance_px and abs(t.y0 - main.y0) < tolerance_px * 2 for t in ticks)
        else:  # vertical
            ticks = horiz_ticks
            has_start = any(abs(t.y0 - main.y0) < tolerance_px and abs(t.x0 - main.x0) < tolerance_px * 2 for t in ticks)
            has_end   = any(abs(t.y0 - main.y1) < tolerance_px and abs(t.x0 - main.x0) < tolerance_px * 2 for t in ticks)
        if not (has_start and has_end):
            continue

        mid_x, mid_y = main.mid
        # Find the closest plausible label.
        best: tuple[float, ExtractedText] | None = None
        for txt in text_objects:
            tx, ty = txt.mid
            if main.orientation == "horizontal":
                # Label should hover above (or on) the main line, horizontally aligned with it.
                dx = abs(tx - mid_x)
                dy = mid_y - ty
                if dx > main.length_px * 0.5 or not (-5 < dy < label_search_px):
                    continue
                dist = math.hypot(dx, dy)
            else:
                dx = tx - mid_x
                dy = abs(ty - mid_y)
                if dy > main.length_px * 0.5 or not (-5 < dx < label_search_px):
                    continue
                dist = math.hypot(dx, dy)
            if best is None or dist < best[0]:
                best = (dist, txt)

        label_text = best[1].text if best else ""
        disp, inches = parse_dimension_text(label_text)
        if best is not None and inches is not None:
            confidence = "high"
        elif best is not None:
            confidence = "medium"
        else:
            confidence = "low"

        results.append(DimensionLine(
            start=(main.x0, main.y0),
            end=(main.x1, main.y1),
            length_px=main.length_px,
            orientation=main.orientation,
            label_text=label_text,
            real_world_value=disp,
            real_world_inches=inches,
            confidence=confidence,
        ))

    # Sort top-to-bottom, left-to-right so downstream formatting is stable.
    results.sort(key=lambda d: (d.start[1], d.start[0]))
    return results


# ---------------------------------------------------------------------------
# Symbol cluster detection
# ---------------------------------------------------------------------------

def _curve_bbox(curve: dict) -> tuple[float, float, float, float] | None:
    pts = curve.get("pts") or []
    if not pts:
        # Fall back to pdfplumber's own bbox when available.
        try:
            return (float(curve["x0"]), float(curve["top"]),
                    float(curve["x1"]), float(curve["bottom"]))
        except (KeyError, ValueError, TypeError):
            return None
    try:
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
    except (IndexError, ValueError, TypeError):
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def detect_symbol_clusters(
    lines: list[ExtractedLine],
    rects: Iterable[dict],
    curves: Iterable[dict],
    min_cluster_size: int = 3,
    max_symbol_px: float = 30.0,
) -> list[SymbolCluster]:
    """Find repeating small shapes that represent construction symbols.

    Identifies:
      - circle_with_cross: small circular curve with ≥2 diagonal lines inside
        → almost always a drilled pile / micropile marker
      - circle_with_line: circle + 1 line → could be a soil nail
      - empty_circle: circle with nothing inside → boring location or column

    Not exhaustive. Vision (Phase 1) still does real symbol recognition; this
    cross-checks it in CAD-exported plans where shapes are vector geometry.
    """
    # Collect small approximately-circular curves.
    circles: list[dict[str, Any]] = []
    for curve in curves:
        bbox = _curve_bbox(curve)
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            continue
        if w > max_symbol_px or h > max_symbol_px:
            continue
        if abs(w - h) > min(w, h) * 0.4:   # drop things that aren't roughly square
            continue
        circles.append({
            "cx": (x0 + x1) / 2,
            "cy": (y0 + y1) / 2,
            "radius": max(w, h) / 2,
            "bbox": bbox,
        })

    clusters: dict[str, list[tuple[float, float, tuple[float, float, float, float]]]] = {}
    for c in circles:
        interior = [
            l for l in lines
            if l.length_px <= c["radius"] * 3
            and abs(l.mid[0] - c["cx"]) < c["radius"]
            and abs(l.mid[1] - c["cy"]) < c["radius"]
        ]
        diagonals = [l for l in interior if l.orientation == "diagonal"]
        if len(diagonals) >= 2:
            sym = "circle_with_cross"
        elif len(interior) >= 1:
            sym = "circle_with_line"
        else:
            sym = "empty_circle"
        clusters.setdefault(sym, []).append((c["cx"], c["cy"], c["bbox"]))

    results: list[SymbolCluster] = []
    for sym, items in clusters.items():
        if len(items) < min_cluster_size:
            continue
        results.append(SymbolCluster(
            symbol_type=sym,
            locations=[(x, y) for x, y, _ in items],
            count=len(items),
            bounding_boxes=[bbox for _, _, bbox in items],
        ))
    return results


# ---------------------------------------------------------------------------
# Scale inference from consistent dimension lines
# ---------------------------------------------------------------------------

def compute_scale_from_geometry(
    dimension_lines: list[DimensionLine],
    page_width: float | None = None,
    page_height: float | None = None,
) -> dict[str, Any] | None:
    """If we have ≥1 high-confidence dimension whose pixel length and real-world
    length are both known, derive the drawing scale. With ≥3 dimensions we
    require agreement within 5% to claim "high" confidence.

    Returns a dict ready to merge into the per-sheet vision context, or
    `None` if no usable dimensions are available.
    """
    usable = [d for d in dimension_lines
              if d.real_world_inches and d.length_px > 20 and d.confidence == "high"]
    if not usable:
        return None

    ratios = sorted(d.real_world_inches / d.length_px for d in usable)
    median = ratios[len(ratios) // 2]
    consistent = [r for r in ratios if abs(r - median) / median < 0.05]
    n = len(consistent)
    confidence = "high" if n >= 3 else "medium" if n >= 1 else "low"

    # PDF points convention: 72 pt/in. If ratios are in real-inches / pt, then
    # 1 drawing inch (72 pt) represents (72 * median) real inches.
    real_inches_per_drawing_inch = median * 72
    scale_text = f'1" = {real_inches_per_drawing_inch / 12:.2f}\' (computed)'

    return {
        "pixels_to_inches": median,
        "real_inches_per_drawing_inch": real_inches_per_drawing_inch,
        "scale_text": scale_text,
        "confidence": confidence,
        "based_on_n_dimensions": n,
        "source": "geometry_computed",
    }


# ---------------------------------------------------------------------------
# Formatter → plain-text context block for Claude
# ---------------------------------------------------------------------------

def _dim_orientation_tag(d: DimensionLine) -> str:
    dx = abs(d.end[0] - d.start[0])
    dy = abs(d.end[1] - d.start[1])
    return "horizontal" if dx > dy else "vertical"


def format_geometry_for_claude(
    dimension_lines: list[DimensionLine],
    symbol_clusters: list[SymbolCluster],
    scale: dict[str, Any] | None,
    page_number: int,
    sheet_label: str = "",
) -> str:
    """Render structured geometry as a compact text block that gets prepended
    to Claude's image analysis. Truncates long cluster lists so the context
    stays a few KB regardless of page complexity.
    """
    out: list[str] = []
    head = f"--- GEOMETRY DATA: Page {page_number}"
    if sheet_label:
        head += f" ({sheet_label})"
    out.append(head + " ---")

    if scale:
        n = scale.get("based_on_n_dimensions", "?")
        out.append(
            f"Scale: {scale.get('scale_text', 'unknown')} "
            f"({scale.get('confidence', '?')} confidence, based on {n} dimensions)"
        )

    if dimension_lines:
        out.append(f"\nDIMENSION LINES ({len(dimension_lines)} found):")
        for i, d in enumerate(dimension_lines[:60], start=1):
            label = d.real_world_value or d.label_text or "(unlabeled)"
            out.append(
                f"  {i}. {label} — {_dim_orientation_tag(d)}, "
                f"length {d.length_px:.0f}px, [{d.confidence}]"
            )
        if len(dimension_lines) > 60:
            out.append(f"  …(+{len(dimension_lines) - 60} more truncated)")

    if symbol_clusters:
        out.append("\nSYMBOL CLUSTERS:")
        for c in symbol_clusters:
            out.append(f"  - {c.symbol_type}: {c.count} instances")
            locs = c.locations[:10]
            loc_str = ", ".join(f"({x:.0f},{y:.0f})" for x, y in locs)
            if c.count > 10:
                loc_str += f", … (+{c.count - 10} more)"
            out.append(f"    Locations: {loc_str}")

    out.append("--- END GEOMETRY DATA ---")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# One-shot convenience: analyze a whole PDF's vector geometry
# ---------------------------------------------------------------------------

@dataclass
class PageGeometry:
    page_index: int
    is_vector: bool
    dimension_lines: list[DimensionLine] = field(default_factory=list)
    symbol_clusters: list[SymbolCluster] = field(default_factory=list)
    scale: dict[str, Any] | None = None
    page_width: float = 0.0
    page_height: float = 0.0

    def to_context_string(self, sheet_label: str = "") -> str:
        return format_geometry_for_claude(
            self.dimension_lines, self.symbol_clusters, self.scale,
            page_number=self.page_index + 1, sheet_label=sheet_label,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "is_vector": self.is_vector,
            "dimension_lines": [asdict(d) for d in self.dimension_lines],
            "symbol_clusters": [asdict(c) for c in self.symbol_clusters],
            "scale": self.scale,
            "page_width": self.page_width,
            "page_height": self.page_height,
        }


def analyze_pdf_geometry(pdf_bytes: bytes) -> list[PageGeometry]:
    """Run the full geometry pipeline on every page of a PDF.

    Each page returns a `PageGeometry`. Scanned pages get `is_vector=False`
    with empty lists — the caller should lean on the vision pipeline for
    those.
    """
    import pdfplumber
    out: list[PageGeometry] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            pg = PageGeometry(
                page_index=i,
                is_vector=is_vector_pdf(page),
                page_width=float(getattr(page, "width", 0) or 0),
                page_height=float(getattr(page, "height", 0) or 0),
            )
            if not pg.is_vector:
                out.append(pg)
                continue
            geom = extract_page_geometry(page)
            pg.dimension_lines = detect_dimension_lines(geom["lines"], geom["text"])
            pg.symbol_clusters = detect_symbol_clusters(geom["lines"], geom["rects"], geom["curves"])
            pg.scale = compute_scale_from_geometry(pg.dimension_lines, pg.page_width, pg.page_height)
            out.append(pg)
    return out


def analyze_pdf_geometry_from_path(pdf_path: str | pathlib.Path) -> list[PageGeometry]:
    return analyze_pdf_geometry(pathlib.Path(pdf_path).read_bytes())
