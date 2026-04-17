"""Main orchestrator for the UMA bid-analysis pipeline.

Usage patterns (all supported so the Tasklet bridge can pick whichever fits):

  1. CLI with JSON on stdin:
       python -m backend.process_bid < payload.json > result.json

  2. CLI with --input <path> and --output-dir <dir>:
       python -m backend.process_bid --input payload.json --output-dir /tmp/out

  3. As a library:
       from backend.process_bid import run_pipeline
       result = run_pipeline(payload, output_dir="/tmp/out")

Input payload (JSON):
  {
    "meta": {
      "name": "string", "location": "string", "client": "string",
      "bid_due_date": "YYYY-MM-DD", "scope_hint": "string", "notes": "string"
    },
    "manual_notes": "string",
    "files": [
      {"name": "file.pdf", "data_base64": "<...>"}, ...
    ],
    "api_key": "optional — overrides ANTHROPIC_API_KEY env var",
    "model": "optional — overrides ANTHROPIC_MODEL env var"
  }

Output (JSON printed to stdout, also written to <output_dir>/result.json):
  {
    "ok": true,
    "output_dir": "/tmp/out",
    "files": [
      {"name": "01_Takeoff.xlsx", "path": "/tmp/out/01_Takeoff.xlsx",
       "size_bytes": 12345, "data_base64": "<...>"}, ...
    ],
    "analysis": { ...the full Claude analysis JSON... },
    "timing": {"ingest_sec": 0.5, "claude_sec": 42.1, "outputs_sec": 0.4, "total_sec": 43.0},
    "usage": {"input_tokens": 0, "output_tokens": 0},
    "model": "claude-sonnet-4-6"
  }

On failure:
  {"ok": false, "error": "string — message", "traceback": "string — optional"}
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
from typing import Any

from .analyze import analyze, DEFAULT_MODEL
from .generate_project_info import build_project_info_docx
from .generate_proposal import build_proposal_docx
from .generate_takeoff import build_takeoff_xlsx
from .generate_vendor_rfqs import build_vendor_rfqs_docx
from .ingest import ingest_many


OUTPUT_NAMES = (
    "01_Takeoff.xlsx",
    "02_Project_Info.docx",
    "03_Vendor_RFQs.docx",
    "04_Cost_Proposal.docx",
)


def _decode_files(files: list[dict[str, Any]]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for f in files or []:
        name = f.get("name") or f.get("filename")
        if not name:
            continue
        if "data_base64" in f:
            data = base64.standard_b64decode(f["data_base64"])
        elif "data" in f and isinstance(f["data"], str):
            data = base64.standard_b64decode(f["data"])
        elif "path" in f:
            data = pathlib.Path(f["path"]).read_bytes()
        else:
            continue
        out.append((name, data))
    return out


def _resolve_api_key(payload: dict[str, Any]) -> str:
    key = payload.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Provide it via the ANTHROPIC_API_KEY "
            "environment variable or the `api_key` field in the JSON payload."
        )
    return key


def _resolve_model(payload: dict[str, Any]) -> str:
    return payload.get("model") or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def run_pipeline(payload: dict[str, Any], output_dir: str | pathlib.Path) -> dict[str, Any]:
    """Run the full pipeline and write the 4 deliverables to output_dir.

    Returns a JSON-serializable dict summarizing the run.
    """
    t0 = time.time()
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = payload.get("meta") or {}
    manual_notes = payload.get("manual_notes") or ""
    files = _decode_files(payload.get("files") or [])
    api_key = _resolve_api_key(payload)
    model = _resolve_model(payload)

    t_ingest_start = time.time()
    ingested = ingest_many(files)
    ingest_sec = time.time() - t_ingest_start

    t_claude_start = time.time()
    analysis = analyze(meta, manual_notes, ingested, api_key=api_key, model=model)
    claude_sec = time.time() - t_claude_start

    t_out_start = time.time()
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
    outputs_sec = time.time() - t_out_start

    usage = (analysis.get("_meta") or {}).get("usage") or {"input_tokens": 0, "output_tokens": 0}

    result = {
        "ok": True,
        "output_dir": str(output_dir),
        "files": file_entries,
        "analysis": analysis,
        "timing": {
            "ingest_sec": round(ingest_sec, 3),
            "claude_sec": round(claude_sec, 3),
            "outputs_sec": round(outputs_sec, 3),
            "total_sec": round(time.time() - t0, 3),
        },
        "usage": usage,
        "model": model,
        "ingest_summaries": [f.text_summary for f in ingested],
    }

    (output_dir / "result.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "files"} | {
            "files": [{kk: vv for kk, vv in f.items() if kk != "data_base64"} for f in file_entries]
        }, indent=2),
        encoding="utf-8",
    )
    return result


def _load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        text = pathlib.Path(input_path).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("Empty input payload.")
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the UMA bid-analysis pipeline.")
    parser.add_argument("--input", help="Path to a JSON payload file (default: stdin).")
    parser.add_argument("--output-dir", default="./out", help="Directory to write deliverables.")
    parser.add_argument(
        "--no-base64",
        action="store_true",
        help="Omit base64 file data from stdout JSON (path references only).",
    )
    args = parser.parse_args()

    try:
        payload = _load_payload(args.input)
        result = run_pipeline(payload, output_dir=args.output_dir)
        if args.no_base64:
            result = {**result, "files": [{k: v for k, v in f.items() if k != "data_base64"} for f in result["files"]]}
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0
    except Exception as e:
        err = {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
        json.dump(err, sys.stdout)
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
