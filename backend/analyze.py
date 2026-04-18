"""Claude API call. Produces the structured JSON dict described in prompts/__init__.py.

Single-call `analyze()` remains the simple path. `analyze_batched()` splits
a too-large ingested file set into Claude-sized batches, runs per-batch
analyses, then runs a final merge pass so the four output generators keep
seeing the same schema regardless of package size.

Vision pipeline (Phase 1 + Phase 2):
  run_vision_pipeline(pdf_bytes, filename) runs geometry extraction
  (free, deterministic) and a 3-pass Claude vision analysis on each plan
  sheet page (classify → extract regions in parallel → merge). The result
  is a list of per-page dicts that analyze() can merge into the main call
  as hard-data context via the `vision_data` kwarg.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
from typing import Any, Callable

from anthropic import Anthropic, AsyncAnthropic

from .ingest import IngestedFile

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 16000
# prompts come from the package constant — no .md file lookup needed on backend.
VISION_PROMPT_DIR = pathlib.Path(__file__).parent / "prompts" / "vision"

# Vision pipeline defaults — keep these modest; plan sets of 20+ pages will
# otherwise fan out to hundreds of Claude calls.
VISION_MAX_PAGES = 15
VISION_CLASSIFY_MAX_PX = 1000 * 750   # Pass 1 — low-res full page
VISION_REGION_MAX_PX = 1920 * 1500    # Pass 2 — per-region detail
VISION_PARALLELISM = 6                # concurrent region/Claude calls


from .prompts import SYSTEM_PROMPT


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT


def _load_vision_prompt(name: str) -> str:
    p = VISION_PROMPT_DIR / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


# Prompt lookup table: sheet_type → (prompt_filename, output_key)
_SHEET_PROMPT_MAP: dict[str, tuple[str, str]] = {
    "plan_view":  ("extract_plan_view.md",  "plan_view"),
    "section":    ("extract_section.md",    "section"),
    "detail":     ("extract_detail.md",     "detail"),
    "schedule":   ("extract_schedule.md",   "schedule"),
    "boring_log": ("extract_boring_log.md", "boring_log"),
    "elevation":  ("extract_section.md",    "section"),  # elevations re-use the section prompt
}


def _build_user_message(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
    vision_data: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compose the user message as a list of content blocks.

    When `vision_data` is provided, it is rendered as an authoritative
    "VISION + GEOMETRY EXTRACTIONS" block at the top of the content — the
    model is told to treat dimensions and counts from that block as primary
    data and use the file content for verification and narrative context.
    """
    blocks: list[dict[str, Any]] = []

    md_lines = [
        "# Project metadata (from estimator Tony)",
        f"- Project name: {metadata.get('name') or '(not provided)'}",
        f"- Location: {metadata.get('location') or '(not provided)'}",
        f"- Client / GC: {metadata.get('client') or '(not provided)'}",
        f"- Bid due date: {metadata.get('bid_due_date') or '(not provided)'}",
        f"- Expected scope: {metadata.get('scope_hint') or '(let the analysis determine)'}",
    ]
    if metadata.get("notes"):
        md_lines += ["", "## Additional notes / assumptions / exclusions from Tony", metadata["notes"]]
    if manual_notes:
        md_lines += ["", "## Manual entries (items not in the uploaded files)", manual_notes]
    blocks.append({"type": "text", "text": "\n".join(md_lines)})

    if vision_data:
        blocks.append({
            "type": "text",
            "text": _format_vision_block(vision_data),
        })

    manifest = "\n".join(f"- {f.filename}" for f in ingested) or "(no files uploaded)"
    blocks.append({"type": "text", "text": f"# Uploaded files\n{manifest}"})

    for f in ingested:
        blocks.append({"type": "text", "text": f"\n\n=== BEGIN FILE: {f.filename} ==="})
        for b in f.content_blocks:
            blocks.append(b)
        blocks.append({"type": "text", "text": f"=== END FILE: {f.filename} ==="})

    blocks.append({
        "type": "text",
        "text": (
            "\n\nNow produce the JSON object per the schema in your system prompt. "
            "Return ONLY the JSON — no prose, no markdown fences. "
            "When the VISION + GEOMETRY EXTRACTIONS block is present, treat its "
            "dimensions and symbol counts as ground truth unless the spec content "
            "directly contradicts them."
        ),
    })
    return blocks


def _format_vision_block(vision_data: list[dict[str, Any]]) -> str:
    """Render vision + geometry results as a structured text block for Claude."""
    parts: list[str] = [
        "# VISION + GEOMETRY EXTRACTIONS",
        "The following structured data was extracted from plan sheets before your analysis.",
        "- `geometry` = exact values read directly from the PDF vector data (deterministic, no AI).",
        "- `vision`   = AI-extracted structured data from rasterized regions of the drawings.",
        "Use these as the PRIMARY source of quantities and dimensions for the takeoff. "
        "Tag each takeoff item's `source` field appropriately "
        "(`dimension_read` for geometry-sourced values, `vision_detected` for AI-sourced, "
        "`estimated` when you had to compute). Set `confidence` to match.",
        "",
    ]
    for v in vision_data:
        parts.append(f"## File: {v.get('filename', '(unknown)')}")
        for page in v.get("pages", []):
            parts.append(
                f"\n### Page {page.get('page_index', 0) + 1}"
                f" — sheet {page.get('sheet_info', {}).get('sheet_number') or '?'}: "
                f"{page.get('sheet_info', {}).get('sheet_title') or '(untitled)'}"
                f"  [{page.get('sheet_info', {}).get('sheet_type', '?')}]"
            )
            geom = page.get("geometry_context")
            if geom:
                parts.append(geom)
            merged = page.get("merged")
            if merged:
                parts.append("#### Extracted structured data (vision pass)")
                parts.append(json.dumps(merged, indent=2, default=str))
        parts.append("")
    return "\n".join(parts)


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"Claude returned non-JSON. First 500 chars:\n{text[:500]}") from e
        return json.loads(text[start : end + 1])


def analyze(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
    api_key: str,
    model: str | None = None,
    *,
    client: Anthropic | None = None,
    vision_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    client = client or Anthropic(api_key=api_key)
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    system = _load_system_prompt()
    user_blocks = _build_user_message(metadata, manual_notes, ingested, vision_data=vision_data)

    resp = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_blocks}],
    )

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = _parse_json_response(text)

    data.setdefault("_meta", {})
    data["_meta"]["model"] = model
    data["_meta"]["usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return data


# ---- Batched analysis for large bid packages ------------------------------

DEFAULT_BATCH_TOKEN_BUDGET = 120_000
DEFAULT_BATCH_FILE_LIMIT = 25


def _estimate_blocks_tokens(blocks: list[dict[str, Any]]) -> int:
    total = 0
    for b in blocks:
        btype = b.get("type")
        if btype == "text":
            total += int(len(b.get("text", "")) / 3.5)
        elif btype == "image":
            data_len = len((b.get("source") or {}).get("data", ""))
            kb = max(1, int(data_len * 3 / 4) // 1024)
            total += kb * 12
        elif btype == "document":
            data_len = len((b.get("source") or {}).get("data", ""))
            kb = max(1, int(data_len * 3 / 4) // 1024)
            total += kb * 180
    return total


def estimate_ingested_tokens(ingested: list[IngestedFile]) -> int:
    return sum(_estimate_blocks_tokens(f.content_blocks) for f in ingested)


def _pack_batches(
    ingested: list[IngestedFile],
    token_budget: int,
    file_limit: int,
) -> list[list[IngestedFile]]:
    batches: list[list[IngestedFile]] = []
    current: list[IngestedFile] = []
    current_tokens = 0
    for f in ingested:
        t = _estimate_blocks_tokens(f.content_blocks)
        if current and (current_tokens + t > token_budget or len(current) >= file_limit):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(f)
        current_tokens += t
    if current:
        batches.append(current)
    return batches


_MERGE_SYSTEM_PROMPT = """You are consolidating multiple partial analyses of the same UMA bid package into a single unified analysis.

You will receive several JSON objects, each produced by analyzing a subset of the bid package files. Your job is to merge them into ONE JSON object matching the same schema.

Rules for merging:
- `project` fields: prefer the most specific non-"unknown" values. If different batches disagree, pick the one with the most detailed description and flag the conflict in `estimating_risks`.
- `file_appendix`: concatenate all entries, de-duplicating by filename.
- `takeoff_items`: concatenate all items. Combine duplicates (same item + unit) by summing quantities, but only when sources are clearly the same item; otherwise keep both and note the duplication in the merged notes field.
- `testing_requirements`: concatenate and de-duplicate by (test_type, reference_spec_section). Sum quantities when obviously the same test.
- `design_requirements`: merge `key_design_inputs_needed` as a de-duplicated union. For the other fields, prefer more specific / non-"unknown" values.
- `unknowns_and_assumptions`: concatenate, de-duplicate by `item`.
- `estimating_risks`: concatenate, de-duplicate by `risk`. Keep the highest severity when merging.
- `equipment_list`: concatenate, de-duplicate by `equipment`. Sum `duration_days` only when sources clearly refer to the same equipment run.
- `vendor_list`: concatenate by `vendor_category`. When the same category appears in multiple batches, merge their `takeoff_items_for_rfq` and `testing_items_for_rfq`, and union `suggested_vendors`.
- `cost_proposal_draft`: take the union of `inclusions`, `exclusions`, `clarifications`. For scalar fields (`pricing_basis`, `payment_terms`, `contingency_pct`, `markup_pct`, `bond_required`, `bid_validity_days`), prefer the most specific value; if conflicting, choose the more conservative (higher contingency, stricter bond). Write a single unified `executive_summary`.

Output MUST be a single JSON object matching the original schema. No prose. No markdown fences.
"""


def _run_merge(
    partials: list[dict[str, Any]],
    metadata: dict[str, Any],
    manual_notes: str,
    client: Anthropic,
    model: str,
) -> dict[str, Any]:
    intro_lines = [
        "# Project metadata",
        f"- Project name: {metadata.get('name') or '(unknown)'}",
        f"- Location: {metadata.get('location') or '(unknown)'}",
        f"- Client / GC: {metadata.get('client') or '(unknown)'}",
        f"- Bid due date: {metadata.get('bid_due_date') or '(unknown)'}",
        f"- Expected scope: {metadata.get('scope_hint') or '(unknown)'}",
    ]
    if metadata.get("notes"):
        intro_lines += ["", "## Tony's notes", metadata["notes"]]
    if manual_notes:
        intro_lines += ["", "## Manual entries", manual_notes]

    blocks: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(intro_lines)}]
    for i, p in enumerate(partials, start=1):
        serialized = json.dumps({k: v for k, v in p.items() if k != "_meta"})
        blocks.append({
            "type": "text",
            "text": f"\n\n=== PARTIAL ANALYSIS {i} of {len(partials)} ===\n{serialized}",
        })
    blocks.append({
        "type": "text",
        "text": (
            "\n\nNow produce ONE merged JSON object following the rules in your "
            "system prompt. Return ONLY the JSON."
        ),
    })

    resp = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=_MERGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": blocks}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    merged = _parse_json_response(text)
    merged.setdefault("_meta", {})
    merged["_meta"]["merge_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return merged


def analyze_batched(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
    api_key: str,
    model: str | None = None,
    *,
    token_budget: int = DEFAULT_BATCH_TOKEN_BUDGET,
    file_limit: int = DEFAULT_BATCH_FILE_LIMIT,
    on_batch: Callable[[int, int, dict[str, Any] | None], None] | None = None,
    vision_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze a large file set in multiple Claude calls, then merge.

    Falls back to a single `analyze()` call when the estimated content
    already fits (saves one round-trip and the merge cost).
    """
    client = Anthropic(api_key=api_key)
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    est = estimate_ingested_tokens(ingested)
    if est <= token_budget or len(ingested) <= 1:
        if on_batch:
            on_batch(1, 1, None)
        return analyze(metadata, manual_notes, ingested, api_key=api_key, model=model,
                       client=client, vision_data=vision_data)

    batches = _pack_batches(ingested, token_budget=token_budget, file_limit=file_limit)
    partials: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0}
    # Vision data is attached to the first batch so the model sees it in the
    # same call as at least some of the source files. Subsequent batches just
    # see the file slice — merge_system_prompt consolidates later.
    for i, batch in enumerate(batches, start=1):
        tagged = {**metadata, "notes": (metadata.get("notes") or "") + f"\n[BATCH {i}/{len(batches)}]"}
        partial = analyze(tagged, manual_notes, batch, api_key=api_key, model=model,
                          client=client, vision_data=vision_data if i == 1 else None)
        partials.append(partial)
        u = (partial.get("_meta") or {}).get("usage") or {}
        totals["input_tokens"] += int(u.get("input_tokens") or 0)
        totals["output_tokens"] += int(u.get("output_tokens") or 0)
        if on_batch:
            on_batch(i, len(batches), u)

    merged = _run_merge(partials, metadata, manual_notes, client, model)
    merge_usage = (merged.get("_meta") or {}).get("merge_usage") or {}
    totals["input_tokens"] += int(merge_usage.get("input_tokens") or 0)
    totals["output_tokens"] += int(merge_usage.get("output_tokens") or 0)

    merged.setdefault("_meta", {})
    merged["_meta"]["model"] = model
    merged["_meta"]["usage"] = totals
    merged["_meta"]["batches"] = len(batches)
    merged["_meta"]["batch_est_tokens"] = est
    return merged


# ---------------------------------------------------------------------------
# Vision pipeline (Phase 1 + Phase 2 integration)
#
# Three Claude passes per plan-sheet page, parallelized per region:
#   1. classify_sheet()       — downsampled full page → sheet type + metadata
#   2. extract_from_regions() — each region + sheet-type-specific prompt
#   3. merge_region_results() — dedupe + cross-check + confidence flags
#
# Geometry extraction (deterministic, no API call) runs first and is
# prepended to every region prompt so Claude sees hard-data dimensions
# before trying to read the image.
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any] | list[Any]:
    """Best-effort JSON parse — tolerates ```json fences and leading prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            start = text.find("[")
        end = max(text.rfind("}"), text.rfind("]"))
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def classify_sheet(
    full_page_b64: str,
    client: AsyncAnthropic,
    model: str,
) -> dict[str, Any]:
    """Pass 1 — classify the sheet from a downsampled full-page image."""
    prompt = _load_vision_prompt("classify_sheet.md")
    resp = await client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": full_page_b64}},
            ],
        }],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return _extract_json(text)
    except Exception:
        return {
            "sheet_type": "general", "sheet_number": None, "sheet_title": None,
            "discipline": "general", "contains_dimensions": False,
            "contains_symbols": False, "contains_boring_logs": False,
            "contains_tables": False, "notes": f"classification failed: {text[:120]}",
        }


async def _extract_region(
    region_name: str,
    region_b64: str,
    sheet_info: dict[str, Any],
    scale_info: dict[str, Any] | None,
    geometry_context: str,
    client: AsyncAnthropic,
    model: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    sheet_type = (sheet_info.get("sheet_type") or "plan_view").lower()
    prompt_file, output_key = _SHEET_PROMPT_MAP.get(sheet_type, ("extract_plan_view.md", "plan_view"))
    prompt = _load_vision_prompt(prompt_file)

    scale_text = ((scale_info or {}).get("scale_text") or "unknown")
    scale_type = ((scale_info or {}).get("scale_type") or "unknown")
    prompt = (
        prompt
        .replace("{scale_text}", scale_text)
        .replace("{scale_type}", scale_type)
        .replace("{geometry_context}", geometry_context or "(no vector geometry available)")
    )
    prompt = f"Region: **{region_name}**\n\n{prompt}"

    async with semaphore:
        resp = await client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": region_b64}},
                ],
            }],
        )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        data = _extract_json(text)
    except Exception:
        data = {"parse_error": text[:500]}
    return {"region": region_name, "output_key": output_key, "data": data,
            "usage": {"input_tokens": resp.usage.input_tokens,
                      "output_tokens": resp.usage.output_tokens}}


async def extract_from_regions(
    regions: dict[str, str],
    sheet_info: dict[str, Any],
    scale_info: dict[str, Any] | None,
    geometry_context: str,
    client: AsyncAnthropic,
    model: str,
    concurrency: int = VISION_PARALLELISM,
) -> list[dict[str, Any]]:
    """Pass 2 — run the sheet-type-specific extraction prompt on every region
    in parallel, bounded by `concurrency` so we don't stampede the API.
    """
    sem = asyncio.Semaphore(concurrency)
    tasks = [
        _extract_region(name, b64, sheet_info, scale_info, geometry_context, client, model, sem)
        for name, b64 in regions.items()
    ]
    return await asyncio.gather(*tasks)


def _merge_arrays_unique(items: list[Any], key_fn: Callable[[Any], str]) -> list[Any]:
    seen: dict[str, Any] = {}
    for it in items:
        try:
            k = key_fn(it)
        except Exception:
            k = json.dumps(it, sort_keys=True, default=str)
        if k not in seen:
            seen[k] = it
    return list(seen.values())


def merge_region_results(
    region_results: list[dict[str, Any]],
    sheet_info: dict[str, Any],
) -> dict[str, Any]:
    """Pass 3 — merge per-region JSON. Dedupe arrays on a best-effort key.

    We do this deterministically rather than with another Claude call to
    keep costs reasonable; the main analyze() call gets the merged output
    plus the geometry block, which is plenty for cross-referencing.
    """
    merged: dict[str, Any] = {"regions_analyzed": [], "_usage": {"input_tokens": 0, "output_tokens": 0}}
    combined_arrays: dict[str, list[Any]] = {}

    for rr in region_results:
        merged["regions_analyzed"].append(rr["region"])
        u = rr.get("usage") or {}
        merged["_usage"]["input_tokens"] += int(u.get("input_tokens") or 0)
        merged["_usage"]["output_tokens"] += int(u.get("output_tokens") or 0)
        data = rr.get("data") or {}
        if not isinstance(data, dict):
            continue
        for k, v in data.items():
            if isinstance(v, list):
                combined_arrays.setdefault(k, []).extend(v)
            elif k not in merged:
                merged[k] = v

    # Best-effort dedupe keys per known array field.
    dedupe_keys: dict[str, Callable[[Any], str]] = {
        "dimensions":             lambda d: f"{d.get('text')}|{d.get('measures')}",
        "other_dimensions":       lambda d: f"{d.get('text')}|{d.get('measures')}",
        "depths":                 lambda d: f"{d.get('text')}|{d.get('measures')}",
        "elevations":             lambda d: f"{d.get('text')}|{d.get('reference')}",
        "soil_layers":            lambda d: f"{d.get('depth_from')}|{d.get('depth_to')}|{d.get('description')[:30] if d.get('description') else ''}",
        "structural_elements":    lambda d: f"{d.get('type')}|{d.get('size')}|{d.get('length')}",
        "pile_or_anchor_symbols": lambda d: f"{d.get('symbol_type')}|{d.get('approximate_location')}",
        "wall_sections":          lambda d: f"{d.get('type')}|{d.get('stations')}|{d.get('length')}",
        "annotations":            lambda d: d.get("text", ""),
        "materials_called_out":   lambda d: f"{d.get('item')}|{d.get('spec')}",
        "reinforcing":            lambda d: f"{d.get('bar_size')}|{d.get('quantity')}|{d.get('length')}",
        "borings":                lambda d: d.get("boring_id", ""),
        "grid_lines":             lambda d: str(d),
        "callouts_referenced":    lambda d: str(d),
    }

    for k, items in combined_arrays.items():
        merge_fn = dedupe_keys.get(k, lambda d: json.dumps(d, sort_keys=True, default=str))
        merged[k] = _merge_arrays_unique(items, merge_fn)

    merged["sheet_info"] = sheet_info
    return merged


async def _analyze_one_page(
    page,  # vision.PreparedPage
    page_geometry,  # geometry.PageGeometry | None
    client: AsyncAnthropic,
    model: str,
) -> dict[str, Any]:
    # Circular-import guard — import lazily so callers who don't use vision
    # pipeline don't need pillow/pdfplumber imported by this module.
    from . import vision as V
    from . import geometry as G

    # Scale detection: try text first, fall back to title-block vision call.
    scale_info = V.detect_scale_from_text(page.page_text)
    if scale_info is None and page_geometry and page_geometry.scale:
        scale_info = G_as_scale(page_geometry.scale)
    if scale_info is None:
        # Final fallback: one small Claude call on the title block crop.
        title_b64 = V.image_to_base64(page.title_block, max_pixels=900 * 600)
        prompt = _load_vision_prompt("extract_scale.md")
        resp = await client.messages.create(
            model=model, max_tokens=1000,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": title_b64}},
            ]}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            parsed = _extract_json(text)
            scale_info = V.ScaleInfo(
                scale_text=parsed.get("scale_text") or "unknown",
                scale_ratio=parsed.get("scale_ratio"),
                scale_type=parsed.get("scale_type") or "none",
                confidence=parsed.get("confidence") or "low",
                source="title_block_vision",
            )
        except Exception:
            scale_info = None

    # Pass 1 — classify on a downsampled full page.
    full_b64 = V.image_to_base64(page.full_image, max_pixels=VISION_CLASSIFY_MAX_PX)
    sheet_info = await classify_sheet(full_b64, client, model)

    # Build geometry context string (empty when page had no vector content).
    sheet_label = f"{sheet_info.get('sheet_number') or ''} {sheet_info.get('sheet_title') or ''}".strip()
    geometry_context = page_geometry.to_context_string(sheet_label) if page_geometry else ""

    # Pass 2 — each region in parallel.
    region_b64 = {name: V.image_to_base64(img, max_pixels=VISION_REGION_MAX_PX)
                  for name, img in page.regions.items()}
    region_results = await extract_from_regions(
        region_b64, sheet_info, scale_info.to_dict() if scale_info else None,
        geometry_context, client, model,
    )

    # Pass 3 — merge.
    merged = merge_region_results(region_results, sheet_info)

    return {
        "page_index": page.page_index,
        "sheet_info": sheet_info,
        "scale_info": scale_info.to_dict() if scale_info else None,
        "geometry_context": geometry_context,
        "merged": merged,
    }


def G_as_scale(geom_scale: dict[str, Any]):
    """Convert a geometry.compute_scale_from_geometry() dict into a ScaleInfo."""
    from . import vision as V
    return V.ScaleInfo(
        scale_text=geom_scale.get("scale_text") or "computed",
        scale_ratio=geom_scale.get("real_inches_per_drawing_inch"),
        scale_type="engineering",
        confidence=geom_scale.get("confidence") or "medium",
        source="geometry",
    )


async def _run_vision_pipeline_async(
    pdf_bytes_list: list[tuple[str, bytes]],
    api_key: str,
    model: str | None = None,
    max_pages_per_file: int = VISION_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Run the full vision pipeline on each PDF. Returns one dict per file:
        {"filename": ..., "pages": [page_result, ...]}
    """
    from . import vision as V
    from . import geometry as G

    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    client = AsyncAnthropic(api_key=api_key)
    out: list[dict[str, Any]] = []

    for filename, data in pdf_bytes_list:
        try:
            # Phase 2 — free geometry extraction first.
            geo_pages = G.analyze_pdf_geometry(data)
        except Exception:
            geo_pages = []

        try:
            prepared = V.prepare_pages(data, max_pages=max_pages_per_file)
        except Exception as e:
            out.append({"filename": filename, "error": f"rasterize failed: {e}", "pages": []})
            continue

        page_results: list[dict[str, Any]] = []
        for p in prepared:
            pg = geo_pages[p.page_index] if p.page_index < len(geo_pages) else None
            try:
                res = await _analyze_one_page(p, pg, client, model)
                page_results.append(res)
            except Exception as e:
                page_results.append({
                    "page_index": p.page_index,
                    "error": f"vision analyze failed: {e}",
                    "geometry_context": pg.to_context_string() if pg else "",
                })
        out.append({"filename": filename, "pages": page_results})
    return out


def run_vision_pipeline(
    pdf_files: list[tuple[str, bytes]],
    api_key: str,
    model: str | None = None,
    max_pages_per_file: int = VISION_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Sync wrapper that runs the async vision pipeline with its own event loop.

    Input: list of (filename, pdf_bytes). Files that look like text-heavy specs
    (rather than plan sheets) should be filtered by the caller via
    `vision.looks_like_plan_sheet()` before calling this function.
    """
    return asyncio.run(_run_vision_pipeline_async(pdf_files, api_key, model, max_pages_per_file))


def filter_plan_sheet_pdfs(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Return only the entries that look like construction drawings."""
    from . import vision as V
    return [(name, data) for name, data in files
            if name.lower().endswith(".pdf") and V.looks_like_plan_sheet(data)]
