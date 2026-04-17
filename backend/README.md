# UMA Estimating — Tasklet Instant App backend

This directory contains the Python backend for the Tasklet Instant App version
of the UMA estimating tool. The frontend lives in the repo root as
`instant-app.html`.

The existing Streamlit app (`app.py`, `src/`) is untouched and still deployable
via Streamlit Cloud — this folder is additive and does not affect it.

## Install

```bash
pip install -r backend/requirements.txt
```

Sets up `anthropic`, `openpyxl`, `python-docx`, `pdfplumber`, `Pillow`, and
`pandas`.

## Run the HTTP backend

The simplest integration is a local HTTP server that serves both the
`instant-app.html` frontend and the `/api/process` endpoint:

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
python3 -m backend.server --port 8787 --output-dir /tmp/uma-out
# open http://localhost:8787/
```

Model defaults to `claude-sonnet-4-6`. Override with `ANTHROPIC_MODEL` env var
or the `model` field in the JSON payload.

## Run the orchestrator as a script

Useful when Tasklet invokes the backend via a per-request subprocess:

```bash
# stdin mode
python3 -m backend.process_bid --output-dir /tmp/uma-out < payload.json > result.json

# file mode
python3 -m backend.process_bid --input payload.json --output-dir /tmp/uma-out
```

## Payload shape

```json
{
  "meta": {
    "name": "Back Bay Underpinning",
    "location": "Boston, MA",
    "client": "Turner Construction",
    "bid_due_date": "2026-05-01",
    "scope_hint": "Micropile",
    "notes": "Exclude dewatering beyond 100 gpm."
  },
  "manual_notes": "Client verbally confirmed 42 piles at 80ft each.",
  "files": [
    {"name": "drawings.pdf", "data_base64": "JVBERi0..."},
    {"name": "geotech.pdf", "data_base64": "JVBERi0..."}
  ],
  "drive_folder": "https://drive.google.com/drive/folders/<ID>",
  "drive_recursive": true
}
```

Either `files` or `drive_folder` (or both) must be provided. `drive_folder`
accepts a bare folder ID or any Drive URL containing one. Server-side
downloads let you process bid packages well beyond browser upload limits.

Response (on success):

```json
{
  "ok": true,
  "output_dir": "/tmp/uma-out",
  "files": [
    {"name": "01_Takeoff.xlsx", "path": "/tmp/uma-out/01_Takeoff.xlsx",
     "size_bytes": 12345, "data_base64": "UEsDBBQ..."},
    {"name": "02_Project_Info.docx", "...": "..."},
    {"name": "03_Vendor_RFQs.docx", "...": "..."},
    {"name": "04_Cost_Proposal.docx", "...": "..."}
  ],
  "analysis": { "...": "full structured JSON from Claude" },
  "timing":  {"ingest_sec": 0.4, "claude_sec": 38.2, "outputs_sec": 0.3, "total_sec": 38.9},
  "usage":   {"input_tokens": 12345, "output_tokens": 6789},
  "model":   "claude-sonnet-4-6"
}
```

On error: `{"ok": false, "error": "...", "traceback": "..."}`.

## Module map

| File | Purpose |
|---|---|
| `prompts.py` | System prompt (mirrors `src/prompts/system.md`) |
| `ingest.py` | PDF / DOCX / XLSX / CSV / image / text → Claude content blocks |
| `analyze.py` | Anthropic API call, JSON parsing |
| `generate_takeoff.py` | Builds `01_Takeoff.xlsx` |
| `generate_project_info.py` | Builds `02_Project_Info.docx` |
| `generate_vendor_rfqs.py` | Builds `03_Vendor_RFQs.docx` |
| `generate_proposal.py` | Builds `04_Cost_Proposal.docx` |
| `process_bid.py` | Orchestrator — JSON in, 4 deliverables out |
| `server.py` | `http.server` wrapper around `process_bid.py` |

## Google Drive integration

Bid packages routinely run 5-10 GB (plan sets, high-res drawings, CAD
exports) — too large for browser upload. The backend downloads from a
Drive folder server-side instead. Users drop files into a Drive folder,
share it with the service account, and paste the folder URL into the UI.

### Service account setup

1. In Google Cloud Console, create a project and enable the **Google Drive
   API**.
2. Create a Service Account with no roles (Drive uses resource-level
   sharing, not IAM).
3. Generate a JSON key for the service account.
4. Share the target Drive folder(s) with the service account's email
   (`…@…iam.gserviceaccount.com`) as **Viewer**. Parent-level sharing
   cascades to subfolders.

### Providing credentials

The backend reads creds in this order:
1. `service_account` field on the request payload (inline JSON string or dict)
2. `GOOGLE_SERVICE_ACCOUNT_JSON` env var (inline JSON)
3. `GOOGLE_APPLICATION_CREDENTIALS` env var (path to the JSON file)

### Supported file types

Regular PDF / DOCX / XLSX / images / TXT files pass through to ingest.
Google-native files are auto-exported:

| Google type  | Exported as |
|---|---|
| Docs         | `.docx` |
| Spreadsheets | `.xlsx` |
| Slides       | `.pdf` |
| Drawings     | `.png` |

Forms, Sites, and Jamboards are skipped with a note.

### Size caps

Defaults: 250 MB per file, 8 GB total. Overridable by passing
`max_file_bytes` in the payload. Files over the cap appear in the
`drive.skipped[]` list in the response with a reason.

## Frontend bridge

`instant-app.html` tries the following integration shapes in order:

1. `window.tasklet.runBackend("process_bid", payload)`
2. `window.tasklet.runScript("backend/process_bid.py", payload)`
3. `window.tasklet.call("process_bid", payload)`
4. `window.tasklet.exec({ script: "backend/process_bid.py", payload })`
5. `fetch("/api/process", { method: "POST", body: JSON.stringify(payload) })`

Whichever the Tasklet host exposes, the app routes through it automatically.
