"""Vision preprocessing for plan-sheet PDFs.

Turns construction plan PDFs into Claude-readable regions:
  - Rasterize each page to PIL.Image at 150 DPI
  - Split the page into 5 overlapping regions (4 quadrants + center strip)
    so dimension text near a region boundary is captured in full by at least
    one neighbor
  - Crop the bottom-right ~20% as a title block (scale + sheet info live here)
  - Base64-encode a region for the Anthropic image block
  - Parse the scale from surrounding text when we can (cheaper than a Claude
    call for scale detection)

Rasterization uses pdf2image when available (poppler-backed, higher quality)
and falls back to pdfplumber's built-in page.to_image() otherwise. pdfplumber
is already a hard dep; pdf2image is optional and adds a poppler runtime
requirement — see SETUP.md.
"""
from __future__ import annotations

import base64
import io
import math
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image


DEFAULT_DPI = 150
HI_RES_DPI = 200
REGION_OVERLAP_PX = 100
MAX_REGION_PIXELS = 1920 * 1500
TITLE_BLOCK_FRACTION = 0.20  # bottom-right 20% of the page


# ---------------------------------------------------------------------------
# PDF → images
# ---------------------------------------------------------------------------

def _rasterize_pdf2image(pdf_bytes: bytes, dpi: int) -> list[Image.Image]:
    """Primary path — pdf2image/poppler. Requires the poppler binary."""
    from pdf2image import convert_from_bytes  # type: ignore
    return convert_from_bytes(pdf_bytes, dpi=dpi, fmt="png")


def _rasterize_pdfplumber(pdf_bytes: bytes, dpi: int) -> list[Image.Image]:
    """Fallback using pdfplumber (pypdfium2 under the hood, no poppler needed)."""
    import pdfplumber
    images: list[Image.Image] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pim = page.to_image(resolution=dpi).original
            # pdfplumber returns a PIL image; ensure RGB for consistent downstream handling.
            if pim.mode != "RGB":
                pim = pim.convert("RGB")
            images.append(pim)
    return images


def pdf_bytes_to_images(pdf_bytes: bytes, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """Rasterize a PDF (as bytes) to one PIL.Image per page.

    Tries pdf2image first (best quality), falls back to pdfplumber. Raises
    `RuntimeError` only if both backends fail.
    """
    try:
        return _rasterize_pdf2image(pdf_bytes, dpi)
    except Exception:
        # pdf2image not installed, or poppler missing — use the pdfplumber path.
        pass
    try:
        return _rasterize_pdfplumber(pdf_bytes, dpi)
    except Exception as e:
        raise RuntimeError(f"Could not rasterize PDF: {e}") from e


def pdf_to_images(pdf_path: str | pathlib.Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    data = pathlib.Path(pdf_path).read_bytes()
    return pdf_bytes_to_images(data, dpi=dpi)


# ---------------------------------------------------------------------------
# Page splitting
# ---------------------------------------------------------------------------

def split_page_into_regions(
    image: Image.Image,
    overlap_px: int = REGION_OVERLAP_PX,
) -> dict[str, Image.Image]:
    """Split a page image into 5 overlapping regions.

    Returns a dict keyed by:
        'top_left', 'top_right', 'bottom_left', 'bottom_right', 'center'

    Quadrants overlap each other by `overlap_px` along the center seam, and
    the 'center' strip captures the middle cross-section where dimensions
    often sit straddling the seam. Each region is capped at ~1920x1500 so
    the Anthropic image blocks stay compact.
    """
    w, h = image.size
    half_w, half_h = w // 2, h // 2
    ov = overlap_px

    regions: dict[str, Image.Image] = {}
    regions["top_left"]     = image.crop((0,            0,            half_w + ov,   half_h + ov))
    regions["top_right"]    = image.crop((half_w - ov,  0,            w,             half_h + ov))
    regions["bottom_left"]  = image.crop((0,            half_h - ov,  half_w + ov,   h))
    regions["bottom_right"] = image.crop((half_w - ov,  half_h - ov,  w,             h))

    # Center strip: middle third horizontally × middle three-fifths vertically.
    cx0, cx1 = int(w * 1/3), int(w * 2/3)
    cy0, cy1 = int(h * 1/5), int(h * 4/5)
    regions["center"] = image.crop((cx0, cy0, cx1, cy1))

    # Downscale any oversized region while preserving aspect ratio.
    for k, img in list(regions.items()):
        regions[k] = _cap_pixels(img, MAX_REGION_PIXELS)
    return regions


def extract_title_block(
    image: Image.Image,
    fraction: float = TITLE_BLOCK_FRACTION,
) -> Image.Image:
    """Crop the bottom-right ~20% of the page — where the title block lives
    on virtually every construction drawing. Used to read scale + sheet info.
    """
    w, h = image.size
    tb_w = int(w * fraction * 2.5)  # the title block is usually wider than tall
    tb_h = int(h * fraction)
    tb_w = min(tb_w, w)
    tb_h = min(tb_h, h)
    return image.crop((w - tb_w, h - tb_h, w, h))


# ---------------------------------------------------------------------------
# Base64 encoding
# ---------------------------------------------------------------------------

def _cap_pixels(image: Image.Image, max_pixels: int) -> Image.Image:
    """Resize (preserving aspect) so total pixel count ≤ max_pixels."""
    w, h = image.size
    if w * h <= max_pixels:
        return image
    scale = math.sqrt(max_pixels / (w * h))
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return image.resize(new_size, Image.LANCZOS)


def image_to_base64(
    image: Image.Image,
    max_pixels: int = MAX_REGION_PIXELS,
    format: str = "PNG",
) -> str:
    """PNG-encode + base64. Line drawings compress badly with JPEG — stick
    with PNG unless the caller has a strong reason to switch.
    """
    img = _cap_pixels(image, max_pixels)
    if format == "PNG" and img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def image_block(image: Image.Image, max_pixels: int = MAX_REGION_PIXELS) -> dict[str, Any]:
    """Return an Anthropic message content block for an image."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": image_to_base64(image, max_pixels=max_pixels),
        },
    }


# ---------------------------------------------------------------------------
# Text-based scale detection
# ---------------------------------------------------------------------------

# Common scale phrasings on construction drawings. Ordered so more specific
# patterns win — e.g., 1/4" = 1'-0" before 1" = 10'.
_NTS_PAT = re.compile(r"\b(N\.?\s*T\.?\s*S\.?|NOT\s+TO\s+SCALE)\b", re.IGNORECASE)
_ARCH_PAT = re.compile(r"""
    (?P<num>\d+(?:/\d+)?)   # 1/4, 1/8, 3/16 etc.
    ["\u2033]\s*=\s*
    (?P<ft>\d+(?:\.\d+)?)\s*
    ['\u2032](?:\s*-?\s*(?P<inch>\d+(?:\.\d+)?)\s*["\u2033])?
""", re.VERBOSE | re.IGNORECASE)
_ENG_PAT = re.compile(r"""
    1\s*["\u2033]\s*=\s*
    (?P<ft>\d+(?:\.\d+)?)\s*
    ['\u2032]
""", re.VERBOSE | re.IGNORECASE)
_METRIC_PAT = re.compile(r"SCALE\s*1\s*:\s*(?P<k>\d+)", re.IGNORECASE)
_SCALE_PREFIX = re.compile(r"(?:SCALE\s*[:\s]*)", re.IGNORECASE)


@dataclass
class ScaleInfo:
    scale_text: str
    scale_ratio: float | None  # inches-of-world per inch-of-drawing
    scale_type: str            # "architectural" | "engineering" | "metric" | "nts" | "none"
    confidence: str            # "high" | "medium" | "low"
    source: str                # "text" | "title_block_vision" | "geometry" | "none"
    raw_match: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale_text": self.scale_text,
            "scale_ratio": self.scale_ratio,
            "scale_type": self.scale_type,
            "confidence": self.confidence,
            "source": self.source,
            "raw_match": self.raw_match,
        }


def _frac_to_float(s: str) -> float:
    if "/" in s:
        a, b = s.split("/", 1)
        return float(a) / float(b)
    return float(s)


def detect_scale_from_text(page_text: str | None) -> ScaleInfo | None:
    """Search extracted page text for a scale annotation. Fast and free.

    Returns `None` if nothing recognizable is found — callers can then fall
    back to a Claude vision call on the title block.
    """
    if not page_text:
        return None
    text = page_text

    if _NTS_PAT.search(text):
        return ScaleInfo("NTS", None, "nts", "high", "text", raw_match="NTS")

    # Architectural (fraction of inch = feet-inches) tends to come first in UMA drawings.
    m = _ARCH_PAT.search(text)
    if m:
        num_raw = m.group("num")
        num_in = _frac_to_float(num_raw)                # drawing inches per fraction
        ft = float(m.group("ft"))
        inch = float(m.group("inch") or 0)
        real_inches = ft * 12 + inch
        ratio = real_inches / num_in if num_in else None
        raw = m.group(0)
        # If num is a whole number (not a fraction) and no trailing inches, it's
        # the engineering form "1" = 10'"; call it that so downstream choices
        # (e.g., rendering grid precision) are correct.
        if "/" not in num_raw and inch == 0:
            sc_type = "engineering"
        else:
            sc_type = "architectural"
        return ScaleInfo(
            scale_text=raw.strip(),
            scale_ratio=ratio,
            scale_type=sc_type,
            confidence="high" if _SCALE_PREFIX.search(text[:m.start() + 20]) else "medium",
            source="text",
            raw_match=raw,
        )

    m = _ENG_PAT.search(text)
    if m:
        ft = float(m.group("ft"))
        ratio = ft * 12  # real inches per drawing inch
        raw = m.group(0)
        return ScaleInfo(
            scale_text=raw.strip(),
            scale_ratio=ratio,
            scale_type="engineering",
            confidence="high" if _SCALE_PREFIX.search(text[:m.start() + 20]) else "medium",
            source="text",
            raw_match=raw,
        )

    m = _METRIC_PAT.search(text)
    if m:
        k = float(m.group("k"))
        # 1:100 means 1 drawing mm = 100 real mm; ratio here is in inches.
        return ScaleInfo(
            scale_text=f"1:{int(k)}",
            scale_ratio=k,  # unitless — caller interprets as "k real units per 1 drawing unit"
            scale_type="metric",
            confidence="high",
            source="text",
            raw_match=m.group(0),
        )

    return None


# ---------------------------------------------------------------------------
# Plan-sheet heuristics
# ---------------------------------------------------------------------------

def looks_like_plan_sheet(pdf_bytes: bytes) -> bool:
    """Fast heuristic: is this a construction drawing PDF or a text-heavy spec?

    Runs one pdfplumber pass and looks at:
      - page count (drawings are usually short)
      - text density (drawings are sparse: <800 chars/page; specs are dense)
      - presence of vector lines (drawings have lots, specs have few)

    We err toward *enabling* vision when in doubt — the cost of a false
    positive is a few extra tokens, the cost of a false negative is a
    takeoff that misses dimensions.
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) == 0:
                return False
            if len(pdf.pages) > 50:
                return False  # huge docs are almost always specs

            char_total = 0
            line_total = 0
            sample = pdf.pages[: min(5, len(pdf.pages))]
            for page in sample:
                char_total += len((page.extract_text() or ""))
                line_total += len(page.lines)
            per_page_chars = char_total / len(sample)
            per_page_lines = line_total / len(sample)
            if per_page_chars < 800 and per_page_lines > 5:
                return True
            if per_page_lines > 100:
                return True  # tons of vector lines → drawing
            return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience: rasterize + region-pack a single plan sheet
# ---------------------------------------------------------------------------

@dataclass
class PreparedPage:
    page_index: int
    full_image: Image.Image
    title_block: Image.Image
    regions: dict[str, Image.Image]
    page_text: str


def prepare_pages(
    pdf_bytes: bytes,
    dpi: int = DEFAULT_DPI,
    max_pages: int | None = None,
) -> list[PreparedPage]:
    """One-shot: rasterize → crop title block → split regions → gather page text.

    Expensive for large plan sets — the caller is expected to have already
    filtered with `looks_like_plan_sheet()`.
    """
    images = pdf_bytes_to_images(pdf_bytes, dpi=dpi)

    page_texts: list[str] = ["" for _ in images]
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i < len(page_texts):
                    page_texts[i] = page.extract_text() or ""
    except Exception:
        pass

    if max_pages is not None:
        images = images[:max_pages]
        page_texts = page_texts[:max_pages]

    out: list[PreparedPage] = []
    for i, img in enumerate(images):
        out.append(PreparedPage(
            page_index=i,
            full_image=img,
            title_block=extract_title_block(img),
            regions=split_page_into_regions(img),
            page_text=page_texts[i] if i < len(page_texts) else "",
        ))
    return out
