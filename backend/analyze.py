"""Claude API call. Produces the structured JSON dict described in prompts.py."""
from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic

from .ingest import IngestedFile
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 16000


def _build_user_message(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
) -> list[dict[str, Any]]:
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
            "Return ONLY the JSON — no prose, no markdown fences."
        ),
    })
    return blocks


def analyze(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
    api_key: str,
    model: str | None = None,
    *,
    client: Anthropic | None = None,
) -> dict[str, Any]:
    client = client or Anthropic(api_key=api_key)
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    user_blocks = _build_user_message(metadata, manual_notes, ingested)

    resp = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_blocks}],
    )

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                raise RuntimeError(f"Claude returned non-JSON. First 500 chars:\n{text[:500]}") from e
        else:
            raise RuntimeError(f"Claude returned non-JSON. First 500 chars:\n{text[:500]}") from e

    data.setdefault("_meta", {})
    data["_meta"]["model"] = model
    data["_meta"]["usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return data


# ---- Batched analysis for large bid packages ------------------------------

# Approximate input-token budget per batch. Leaves generous room for the
# system prompt, metadata, and for Claude's own processing. Real context
# window is ~200K for Sonnet 4.6; 120K leaves >70K of safety.
DEFAULT_BATCH_TOKEN_BUDGET = 120_000
DEFAULT_BATCH_FILE_LIMIT = 25


def _estimate_blocks_tokens(blocks: list[dict[str, Any]]) -> int:
    """Rough estimate mirroring drive._estimate_tokens but for already-ingested content."""
    total = 0
    for b in blocks:
        btype = b.get("type")
        if btype == "text":
            total += int(len(b.get("text", "")) / 3.5)
        elif btype == "image":
            # base64 data: ~3/4 byte ratio → estimate file KB, then ~12 tok/KB.
            data_len = len((b.get("source") or {}).get("data", ""))
            kb = max(1, int(data_len * 3 / 4) // 1024)
            total += kb * 12
        elif btype == "document":
            data_len = len((b.get("source") or {}).get("data", ""))
            kb = max(1, int(data_len * 3 / 4) // 1024)
            total += kb * 180
    return total


def estimate_ingested_tokens(ingested: list[IngestedFile]) -> int:
    """Public helper: total token estimate across a list of ingested files."""
    return sum(_estimate_blocks_tokens(f.content_blocks) for f in ingested)


def _pack_batches(
    ingested: list[IngestedFile],
    token_budget: int,
    file_limit: int,
) -> list[list[IngestedFile]]:
    """Greedy bin-packing — keep each batch under both budgets."""
    batches: list[list[IngestedFile]] = []
    current: list[IngestedFile] = []
    current_tokens = 0
    for f in ingested:
        t = _estimate_blocks_tokens(f.content_blocks)
        if current and (
            current_tokens + t > token_budget or len(current) >= file_limit
        ):
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
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        merged = json.loads(text)
    except json.JSONDecodeError as e:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise RuntimeError(f"Merge returned non-JSON. First 500 chars:\n{text[:500]}") from e
        merged = json.loads(text[start : end + 1])

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
    on_batch: Any = None,   # optional callback: on_batch(i, total, usage_dict)
) -> dict[str, Any]:
    """Analyze a large file set in multiple Claude calls, then merge.

    If the estimated content fits in one call (or there is only one file),
    runs `analyze()` directly — the merge step would just add latency and
    cost.
    """
    client = Anthropic(api_key=api_key)
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    est = estimate_ingested_tokens(ingested)
    if est <= token_budget or len(ingested) <= 1:
        if on_batch:
            on_batch(1, 1, None)
        return analyze(metadata, manual_notes, ingested, api_key=api_key, model=model, client=client)

    batches = _pack_batches(ingested, token_budget=token_budget, file_limit=file_limit)
    partials: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0}
    for i, batch in enumerate(batches, start=1):
        # Tag the metadata so each partial knows its slice.
        tagged_meta = {**metadata, "notes": (metadata.get("notes") or "") + f"\n[BATCH {i}/{len(batches)}]"}
        partial = analyze(tagged_meta, manual_notes, batch, api_key=api_key, model=model, client=client)
        partials.append(partial)
        usage = (partial.get("_meta") or {}).get("usage") or {}
        totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        totals["output_tokens"] += int(usage.get("output_tokens") or 0)
        if on_batch:
            on_batch(i, len(batches), usage)

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
