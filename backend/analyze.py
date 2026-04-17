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
) -> dict[str, Any]:
    client = Anthropic(api_key=api_key)
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
