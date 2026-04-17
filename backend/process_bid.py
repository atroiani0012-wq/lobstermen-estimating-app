"""Main orchestrator for the UMA bid-analysis pipeline.

Two distinct operations:

  1. scan_drive(payload) — list a Drive folder, return metadata + estimates
     so the UI can let the user pick which files to process.

  2. run_pipeline(payload, output_dir, emit=...) — stream-download each
     selected file, ingest it, discard raw bytes, then run (batched) Claude
     analysis and generate the 4 deliverables. `emit` is an optional
     callback that receives progress events so a streaming HTTP endpoint
     can relay them to the browser.

Both operations are JSON-in / JSON-out so they can be driven from Tasklet's
bridge, the companion HTTP server, or a plain CLI.

CLI:
    python -m backend.process_bid --input payload.json --output-dir ./out
    python -m backend.process_bid --scan --input scan_payload.json  > scan.json

Scan payload:
  {
    "drive_folder": "<URL or ID>",
    "drive_recursive": true,
    "service_account": "<optional inline JSON>"
  }

Run payload (either `files` or `drive_selection` or both):
  {
    "meta": { ...project metadata... },
    "manual_notes": "string",
    "files":  [{"name": "...", "data_base64": "..."}, ...],
    "drive_selection": [
      {"id": "<fileId>", "name": "...", "path": "...",
       "mime_type": "...", "google_native": false, "export_mime": null, ...}
    ],
    "service_account": "<optional>",
    "max_file_bytes":  250000000,
    "max_total_bytes": 2147483648,
    "max_files":       100,
    "override_caps":   false,
    "api_key": "<optional>",
    "model": "<optional>"
  }
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import time
import traceback
from typing import Any, Callable

from .analyze import (
    DEFAULT_MODEL,
    analyze_batched,
    estimate_ingested_tokens,
)
from .generate_project_info import build_project_info_docx
from .generate_proposal import build_proposal_docx
from .generate_takeoff import build_takeoff_xlsx
from .generate_vendor_rfqs import build_vendor_rfqs_docx
from .ingest import ingest_file, ingest_many


OUTPUT_NAMES = (
    "01_Takeoff.xlsx",
    "02_Project_Info.docx",
    "03_Vendor_RFQs.docx",
    "04_Cost_Proposal.docx",
)

# Defaults — overridable per-request.
DEFAULT_MAX_FILE_BYTES = 250 * 1024 * 1024        # 250 MB per file
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB of source files
DEFAULT_MAX_FILES = 100

# Anthropic Sonnet 4.6 price ballpark. Update when pricing changes.
PRICE_INPUT_PER_MTOK = 3.0
PRICE_OUTPUT_PER_MTOK = 15.0


# ---- Helpers --------------------------------------------------------------

Emit = Callable[[dict[str, Any]], None]


def _noop_emit(_event: dict[str, Any]) -> None:
    pass


def _emit(emit: Emit | None, event: dict[str, Any]) -> None:
    (emit or _noop_emit)(event)


def _resolve_api_key(payload: dict[str, Any]) -> str:
    key = payload.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Provide it via the ANTHROPIC_API_KEY "
            "env var or the `api_key` field in the JSON payload."
        )
    return key


def _resolve_model(payload: dict[str, Any]) -> str:
    return payload.get("model") or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _decode_uploaded(files: list[dict[str, Any]]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for f in files or []:
        name = f.get("name") or f.get("filename")
        if not name:
            continue
        if "data_base64" in f:
            out.append((name, base64.standard_b64decode(f["data_base64"])))
        elif isinstance(f.get("data"), str):
            out.append((name, base64.standard_b64decode(f["data"])))
        elif "path" in f:
            out.append((name, pathlib.Path(f["path"]).read_bytes()))
    return out


def _load_creds_override(payload: dict[str, Any]):
    override = payload.get("service_account")
    if override is None:
        return None
    from .drive import _load_credentials
    return _load_credentials(override)


def _estimate_cost(input_tokens: int, output_tokens: int) -> dict[str, Any]:
    input_cost = (input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK
    output_cost = (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "input_cost_usd": round(input_cost, 3),
        "output_cost_usd": round(output_cost, 3),
        "total_cost_usd": round(input_cost + output_cost, 3),
    }


# ---- Scan -----------------------------------------------------------------

def scan_drive(payload: dict[str, Any]) -> dict[str, Any]:
    """List a Drive folder and return a JSON tree of files plus estimates."""
    from .drive import scan_folder

    folder = payload.get("drive_folder")
    if not folder:
        raise RuntimeError("Missing `drive_folder` in payload.")

    creds = _load_creds_override(payload)
    recursive = payload.get("drive_recursive", True)
    scan = scan_folder(folder, recursive=recursive, creds=creds)

    # Estimate assumes selecting ALL supported files (user will refine).
    supported = [f for f in scan.files if f["kind"] == "supported"]
    est_input = sum(f["est_tokens"] for f in supported)
    # Assume ~3K output tokens per batch of ~25 supported files.
    est_output = max(3000, 3000 * ((len(supported) // 25) + 1))

    return {
        "ok": True,
        "folder_id": scan.folder_id,
        "folder_name": scan.folder_name,
        "files": scan.files,
        "counts": {
            "total": len(scan.files),
            "supported": sum(1 for f in scan.files if f["kind"] == "supported"),
            "cad": sum(1 for f in scan.files if f["kind"] == "cad"),
            "media": sum(1 for f in scan.files if f["kind"] == "media"),
            "archive": sum(1 for f in scan.files if f["kind"] == "archive"),
            "other": sum(1 for f in scan.files if f["kind"] == "other"),
            "skipped": sum(1 for f in scan.files if f["kind"] == "skipped"),
        },
        "total_size_bytes": scan.total_size_bytes,
        "estimate_if_all_supported_selected": {
            **_estimate_cost(est_input, est_output),
            "supported_file_count": len(supported),
        },
    }


# ---- Stream-download + ingest --------------------------------------------

def _enforce_caps(
    drive_selection: list[dict[str, Any]],
    max_file_bytes: int,
    max_total_bytes: int,
    max_files: int,
    override: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split selected Drive files into (accepted, rejected-with-reasons)."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    total = 0
    for f in drive_selection:
        if not override and len(accepted) >= max_files:
            rejected.append({**f, "skipped_reason": f"max_files limit of {max_files} reached"})
            continue
        size = int(f.get("size_bytes") or 0)
        if not override and size > max_file_bytes:
            rejected.append({**f, "skipped_reason": f"file size {size} exceeds max_file_bytes {max_file_bytes}"})
            continue
        if not override and total + size > max_total_bytes:
            rejected.append({**f, "skipped_reason": "max_total_bytes cap reached"})
            continue
        accepted.append(f)
        total += size
    return accepted, rejected


def _stream_drive_files(
    drive_selection: list[dict[str, Any]],
    creds,
    emit: Emit | None,
) -> list[Any]:
    """Download each selected Drive file one at a time, ingest it, drop raw bytes.

    Returns the list of IngestedFile objects accumulated across the stream.
    """
    from .drive import download_one
    from .drive import _build_service

    service = _build_service(creds)
    ingested: list[Any] = []
    total_bytes = 0

    for idx, f in enumerate(drive_selection, start=1):
        _emit(emit, {
            "type": "file_start",
            "index": idx,
            "total": len(drive_selection),
            "name": f.get("name"),
            "path": f.get("path") or "",
            "size_bytes": int(f.get("size_bytes") or 0),
        })
        try:
            display_name, data = download_one(f, service=service)
            total_bytes += len(data)
            one = ingest_file(display_name, data)
            # Free the raw bytes aggressively; ingest already copied what it needs.
            del data
            ingested.append(one)
            _emit(emit, {
                "type": "file_done",
                "index": idx,
                "total": len(drive_selection),
                "name": display_name,
                "summary": one.text_summary,
                "cumulative_bytes": total_bytes,
            })
        except Exception as e:
            _emit(emit, {
                "type": "file_error",
                "index": idx,
                "total": len(drive_selection),
                "name": f.get("name"),
                "error": str(e),
            })
            # skip and continue
            continue
    return ingested


# ---- Main pipeline --------------------------------------------------------

def run_pipeline(
    payload: dict[str, Any],
    output_dir: str | pathlib.Path,
    emit: Emit | None = None,
) -> dict[str, Any]:
    """Run the full pipeline. If `emit` is provided, receives progress events.

    Event shapes (all have "type"):
      {type: "start"}
      {type: "cap_enforced", accepted: int, rejected: [...]}
      {type: "file_start", index, total, name, path, size_bytes}
      {type: "file_done",  index, total, name, summary, cumulative_bytes}
      {type: "file_error", index, total, name, error}
      {type: "ingest_done", ingested_count, est_input_tokens}
      {type: "claude_start", batches_planned}
      {type: "claude_batch_done", batch, total_batches, usage}
      {type: "claude_done", usage}
      {type: "outputs_start"}
      {type: "outputs_done"}
      {type: "complete", result: <final dict>}
    """
    t0 = time.time()
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _emit(emit, {"type": "start"})

    meta = payload.get("meta") or {}
    manual_notes = payload.get("manual_notes") or ""
    api_key = _resolve_api_key(payload)
    model = _resolve_model(payload)

    max_file_bytes = int(payload.get("max_file_bytes") or DEFAULT_MAX_FILE_BYTES)
    max_total_bytes = int(payload.get("max_total_bytes") or DEFAULT_MAX_TOTAL_BYTES)
    max_files = int(payload.get("max_files") or DEFAULT_MAX_FILES)
    override = bool(payload.get("override_caps"))

    # 1) Uploaded files (direct drag-drop) — in-memory ingest, same as v1.
    uploaded_bytes = _decode_uploaded(payload.get("files") or [])
    uploaded_ingested = ingest_many(uploaded_bytes)

    # 2) Drive-selected files — stream-download one at a time.
    drive_selection = payload.get("drive_selection") or []
    accepted, rejected = _enforce_caps(
        drive_selection,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_files=max_files,
        override=override,
    )
    _emit(emit, {"type": "cap_enforced", "accepted": len(accepted), "rejected": rejected})

    t_stream = time.time()
    drive_ingested: list[Any] = []
    if accepted:
        creds = _load_creds_override(payload)
        drive_ingested = _stream_drive_files(accepted, creds=creds, emit=emit)
    stream_sec = time.time() - t_stream

    ingested = uploaded_ingested + drive_ingested
    if not ingested and not manual_notes.strip() and not meta.get("notes", "").strip():
        raise RuntimeError(
            "No files were processed and no manual notes provided — nothing to analyze."
        )

    est_in = estimate_ingested_tokens(ingested)
    _emit(emit, {
        "type": "ingest_done",
        "ingested_count": len(ingested),
        "est_input_tokens": est_in,
    })

    # 3) Analyze (batched when the file set is too large for one call).
    t_claude = time.time()

    def _on_batch(i, total, usage):
        _emit(emit, {
            "type": "claude_batch_done",
            "batch": i,
            "total_batches": total,
            "usage": usage or {},
        })

    _emit(emit, {"type": "claude_start", "est_input_tokens": est_in})
    analysis = analyze_batched(
        meta, manual_notes, ingested,
        api_key=api_key, model=model, on_batch=_on_batch,
    )
    claude_sec = time.time() - t_claude
    usage = (analysis.get("_meta") or {}).get("usage") or {"input_tokens": 0, "output_tokens": 0}
    _emit(emit, {"type": "claude_done", "usage": usage})

    # 4) Generate deliverables.
    _emit(emit, {"type": "outputs_start"})
    t_out = time.time()
    builders = {
        "01_Takeoff.xlsx": build_takeoff_xlsx,
        "02_Project_Info.docx": build_project_info_docx,
        "03_Vendor_RFQs.docx": build_vendor_rfqs_docx,
        "04_Cost_Proposal.docx": build_proposal_docx,
    }
    file_entries: list[dict[str, Any]] = []
    for name, builder in builders.items():
        data = builder(analysis)
        path = output_dir / name
        path.write_bytes(data)
        file_entries.append({
            "name": name,
            "path": str(path),
            "size_bytes": len(data),
            "data_base64": base64.standard_b64encode(data).decode("ascii"),
        })
    outputs_sec = time.time() - t_out
    _emit(emit, {"type": "outputs_done"})

    result = {
        "ok": True,
        "output_dir": str(output_dir),
        "files": file_entries,
        "analysis": analysis,
        "timing": {
            "drive_stream_sec": round(stream_sec, 3),
            "claude_sec": round(claude_sec, 3),
            "outputs_sec": round(outputs_sec, 3),
            "total_sec": round(time.time() - t0, 3),
        },
        "usage": usage,
        "cost": _estimate_cost(
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
        ),
        "model": model,
        "batches": (analysis.get("_meta") or {}).get("batches", 1),
        "ingest_summaries": [f.text_summary for f in ingested],
        "drive": {
            "used": bool(accepted),
            "accepted_count": len(accepted),
            "rejected": rejected,
        },
    }
    (output_dir / "result.json").write_text(
        json.dumps({
            **{k: v for k, v in result.items() if k != "files"},
            "files": [{kk: vv for kk, vv in f.items() if kk != "data_base64"} for f in file_entries],
        }, indent=2),
        encoding="utf-8",
    )
    _emit(emit, {"type": "complete", "result": result})
    return result


# ---- CLI ------------------------------------------------------------------

def _load_payload(input_path: str | None) -> dict[str, Any]:
    text = pathlib.Path(input_path).read_text(encoding="utf-8") if input_path else sys.stdin.read()
    if not text.strip():
        raise RuntimeError("Empty input payload.")
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="UMA bid-analysis pipeline.")
    parser.add_argument("--input", help="Path to a JSON payload file (default: stdin).")
    parser.add_argument("--output-dir", default="./out", help="Directory for deliverables.")
    parser.add_argument("--scan", action="store_true", help="Run scan_drive instead of the full pipeline.")
    parser.add_argument("--no-base64", action="store_true", help="Omit file data from stdout JSON.")
    args = parser.parse_args()

    try:
        payload = _load_payload(args.input)
        if args.scan:
            result = scan_drive(payload)
        else:
            result = run_pipeline(payload, output_dir=args.output_dir)
            if args.no_base64:
                result = {**result, "files": [
                    {k: v for k, v in f.items() if k != "data_base64"} for f in result["files"]
                ]}
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0
    except Exception as e:
        json.dump({"ok": False, "error": str(e), "traceback": traceback.format_exc()}, sys.stdout)
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
