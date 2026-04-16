"""
Claude API call. Produces the structured JSON dict described in prompts/system.md.

Now with Anthropic server-side web_search tool enabled — Claude can research the
project (owner, bidder's list, public lettings, news) during analysis.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any, Callable

from anthropic import Anthropic

from .ingest import IngestedFile

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 16000

# Web search tool — Anthropic server-side. Let Claude do the research loop.
# Capped to keep runtime reasonable and avoid runaway tool calls.
DEFAULT_WEB_SEARCH_MAX_USES = 15

PROMPT_PATH = pathlib.Path(__file__).parent / "prompts" / "system.md"
INDUSTRY_KB_PATH = pathlib.Path(__file__).parent / "prompts" / "industry_knowledge.md"


def _load_system_prompt() -> str:
    """Load UMA institutional prompt + industry knowledge pack as a single system message."""
    uma = PROMPT_PATH.read_text(encoding="utf-8")
    parts = [uma]
    if INDUSTRY_KB_PATH.exists():
        industry = INDUSTRY_KB_PATH.read_text(encoding="utf-8")
        parts.append(
            "\n\n---\n\n"
            "# APPENDIX — Industry Knowledge Reference\n\n"
            "The following is authoritative industry reference material (FHWA, AASHTO, ASTM, "
            "CSI, AACE, state DOT standards, subcontracting law, geotech methods). Use it to "
            "sanity-check UMA numbers, cite standards when justifying assumptions, and flag "
            "state-specific risks. UMA institutional data (above) takes precedence when the two "
            "conflict on UMA-specific scopes.\n\n"
            + industry
        )
    return "".join(parts)


def _build_user_message(metadata: dict[str, Any], manual_notes: str, ingested: list[IngestedFile]) -> list[dict[str, Any]]:
    """Compose the user message as a list of content blocks."""
    blocks: list[dict[str, Any]] = []

    md_lines = [
        "# Project metadata (from estimator Tony)",
        f"- Project name: {metadata.get('name') or '(not provided)'}",
        f"- Location: {metadata.get('location') or '(not provided)'}",
        f"- Client / GC: {metadata.get('client') or '(not provided — USE WEB SEARCH to find a prospective bidder list)'}",
        f"- Bid due date: {metadata.get('bid_due_date') or '(not provided)'}",
        f"- Expected scope: {metadata.get('scope_hint') or '(let the analysis determine)'}",
    ]
    if metadata.get("notes"):
        md_lines += ["", "## Additional notes / assumptions / exclusions from Tony", metadata["notes"]]
    if manual_notes:
        md_lines += ["", "## Manual entries (items not in the uploaded files)", manual_notes]
    blocks.append({"type": "text", "text": "\n".join(md_lines)})

    # Web-research directives — fire these searches in parallel with file analysis.
    research_directives = [
        "# Web research directives (execute in parallel with file analysis)",
        "",
        "Use the web_search tool aggressively. Target up to 15 searches. Prioritize:",
        "",
        "1. **Project context** — search the project name + location. Find owner, EOR (engineer of record), "
        "budget, schedule, any public news or press releases.",
        "2. **Bidder's list / plan-holders** — if the client/GC is unknown OR even if known (to cross-verify), "
        "search for the project on state DOT letting pages (VDOT, NCDOT, SCDOT, VDOT iPM), federal SAM.gov, "
        "regional plan rooms, or the owner's procurement site. Many public projects publish a 'plan-holders list' "
        "or 'prospective bidders list' that names every GC who requested bid docs. Extract every GC name, "
        "location, and contact if visible. Also check for a Pre-Bid Meeting sign-in sheet if posted.",
        "3. **Spec callouts** — if the bid references an unusual spec (e.g., 'VDOT Section 414', 'NCDOT DN12200752'), "
        "search for the current version to confirm testing/design requirements.",
        "4. **Vendor availability** — if a bid requires a specific product (e.g., 'GR80 hollow bar' or 'self-drilling anchors'), "
        "confirm vendor availability and catalog pricing on public data.",
        "",
        "Put every bidder you find into `web_research.bidder_list` with fields: company_name, location, "
        "contact_name, contact_email, contact_phone, source_url. This feeds a 5th output spreadsheet.",
        "",
        "Put any other useful research findings into `web_research.findings` as short citations.",
    ]
    blocks.append({"type": "text", "text": "\n".join(research_directives)})

    # File manifest
    manifest = "\n".join(f"- {f.filename}" for f in ingested) or "(no files uploaded)"
    blocks.append({"type": "text", "text": f"# Uploaded files\n{manifest}"})

    # Each file's extracted content
    for f in ingested:
        blocks.append({"type": "text", "text": f"\n\n=== BEGIN FILE: {f.filename} ==="})
        for b in f.content_blocks:
            blocks.append(b)
        blocks.append({"type": "text", "text": f"=== END FILE: {f.filename} ==="})

    blocks.append({
        "type": "text",
        "text": (
            "\n\nNow perform web research (in parallel) and produce the JSON object per the schema in your "
            "system prompt. Return ONLY the JSON — no prose, no markdown fences."
        ),
    })
    return blocks


def analyze(
    metadata: dict[str, Any],
    manual_notes: str,
    ingested: list[IngestedFile],
    api_key: str,
    model: str | None = None,
    enable_web_search: bool = True,
    web_search_max_uses: int = DEFAULT_WEB_SEARCH_MAX_USES,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    client = Anthropic(api_key=api_key)
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    def _emit(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    system = _load_system_prompt()
    user_blocks = _build_user_message(metadata, manual_notes, ingested)

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_blocks}],
    }
    if enable_web_search:
        kwargs["tools"] = [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": web_search_max_uses,
            }
        ]
        _emit(f"🌐 Web search enabled (cap {web_search_max_uses} queries)")

    t_start = time.time()
    _emit("📤 Sending to Claude…")
    resp = client.messages.create(**kwargs)
    elapsed = time.time() - t_start
    _emit(f"   ✅ Claude responded in {elapsed:.1f}s")

    # Extract text from the final assistant message. Server-side web_search returns
    # tool_use + tool_result blocks interleaved — we only want the final text blocks.
    text_parts: list[str] = []
    web_searches_run = 0
    for b in resp.content:
        btype = getattr(b, "type", None)
        if btype == "text":
            text_parts.append(b.text)
        elif btype == "server_tool_use":
            web_searches_run += 1
            name = getattr(b, "name", "")
            if name == "web_search":
                inp = getattr(b, "input", {}) or {}
                query = inp.get("query", "") if isinstance(inp, dict) else ""
                _emit(f"   🔎 web_search: {query[:80]}")
        elif btype == "web_search_tool_result":
            # Claude already processed these; we don't need to act on them.
            pass
    if web_searches_run:
        _emit(f"   🌐 {web_searches_run} web search(es) executed")

    text = "".join(text_parts).strip()
    # Strip accidental fences if the model adds them despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Best-effort: find the first { and last } and try again.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                raise RuntimeError(f"Claude returned non-JSON. First 500 chars:\n{text[:500]}") from e
        else:
            raise RuntimeError(f"Claude returned non-JSON. First 500 chars:\n{text[:500]}") from e

    # Stash metadata for downstream generators.
    data.setdefault("_meta", {})
    data["_meta"]["model"] = model
    data["_meta"]["usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    data["_meta"]["web_searches_run"] = web_searches_run
    data["_meta"]["analyze_elapsed_sec"] = round(elapsed, 1)
    return data
