"""Lobstermen Estimating App — Streamlit entry point.

Flow:
  1. Landing → "Create New Estimate"
  2. Create Estimate page: project metadata + (Google Drive folder OR drag-drop)
     + manual notes
  3. Analyze & Generate → Claude call(s) → 4 downloadable outputs

Two file-input modes:
  - Direct upload (handful of files, <~200 MB each) — original flow
  - Google Drive folder — scan → select → stream one file at a time.
    Needed for real bid packages (5-10 GB) that would blow the browser's or
    Streamlit Cloud's upload limits.
"""
from __future__ import annotations

import base64
import datetime as _dt
import io
import json
import os
import time
from typing import Any

import streamlit as st

from src.ingest import ingest_many, ingest_file
from src.analyze import (
    analyze, analyze_batched, estimate_ingested_tokens, DEFAULT_MODEL,
    run_vision_pipeline, filter_plan_sheet_pdfs,
)
from src.outputs.takeoff import build_takeoff_xlsx
from src.outputs.project_info import build_project_info_docx
from src.outputs.vendor_rfqs import build_vendor_rfqs_docx
from src.outputs.proposal import build_proposal_docx


# Anthropic Sonnet 4.6 price ballpark (per million tokens). Update here when it changes.
PRICE_INPUT_PER_MTOK = 3.0
PRICE_OUTPUT_PER_MTOK = 15.0

# Safety defaults — user can override in the UI.
DEFAULT_MAX_FILE_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_FILES = 100


st.set_page_config(
    page_title="Lobstermen Estimating",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- Session state init ---------------------------------------------------------

for key, default in [
    ("view", "landing"),
    ("analysis", None),
    ("outputs", None),
    ("meta", {}),
    ("manual_notes", ""),
    ("files", []),
    ("error", None),
    ("drive_scan", None),        # {folder_id, folder_name, files, counts, ...}
    ("drive_selected", set()),   # set of file IDs
    ("drive_folder_input", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def _goto(view: str) -> None:
    st.session_state.view = view
    st.rerun()


def _get_api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


def _get_model() -> str:
    try:
        m = st.secrets.get("ANTHROPIC_MODEL")
        if m:
            return m
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _drive_creds():
    """Return a google-auth Credentials object, or None if not configured."""
    # Streamlit secrets → dict preferred, then env fallbacks in drive._load_credentials.
    info = None
    try:
        sa = st.secrets.get("google_service_account")
        if sa:
            info = dict(sa) if not isinstance(sa, dict) else sa
    except Exception:
        info = None
    from src.drive import _load_credentials
    return _load_credentials(info)


def _format_bytes(n: int) -> str:
    if not n or n < 0: return "0 B"
    if n < 1024: return f"{n} B"
    if n < 1024 ** 2: return f"{n/1024:.1f} KB"
    if n < 1024 ** 3: return f"{n/1024/1024:.1f} MB"
    return f"{n/1024/1024/1024:.2f} GB"


def _format_tokens(n: int) -> str:
    if not n: return "0"
    if n < 1000: return str(n)
    if n < 1_000_000: return f"{n/1000:.0f}K"
    return f"{n/1_000_000:.2f}M"


def _estimate_cost(input_tok: int, output_tok: int) -> dict[str, Any]:
    ic = (input_tok / 1_000_000) * PRICE_INPUT_PER_MTOK
    oc = (output_tok / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    return {"input_cost": ic, "output_cost": oc, "total_cost": ic + oc}


# --- Views ----------------------------------------------------------------------

def view_landing() -> None:
    st.markdown("# 🦞 Lobstermen Estimating")
    st.markdown("##### AI-powered batch project analyzer for UMA geotechnical bids")
    st.write("")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("### Start")
        if st.button("➕  Create New Estimate", type="primary", use_container_width=True):
            _goto("create")
        if st.button("📁  Past Estimates (coming soon)", use_container_width=True, disabled=True):
            pass

    with col2:
        st.markdown("### What you get")
        st.markdown(
            "- **Takeoff spreadsheet** (.xlsx) — UMA template layout, paste into your master estimator\n"
            "- **Project Info brief** (.docx) — scope summary, tests, design, unknowns, risks, equipment, vendors\n"
            "- **Vendor RFQ drafts** (.docx) — one section per vendor, project-specific quantities\n"
            "- **First-draft Cost Proposal** (.docx)"
        )

    with st.expander("System status"):
        key = _get_api_key()
        st.write("**Anthropic API key:**", "✅ configured" if key else "❌ missing — set ANTHROPIC_API_KEY in secrets")
        st.write("**Model:**", _get_model())
        st.write("**Max direct upload:**", "1 GB per file (drag-drop)")
        try:
            _drive_creds()
            st.write("**Google Drive integration:**", "✅ service account configured")
        except Exception as e:
            st.write("**Google Drive integration:**", f"❌ {e}")


def _render_drive_tab(api_key: str) -> list[tuple[str, bytes]]:
    """Handles the Drive folder scan + selection. Returns a list of
    `(display_name, bytes)` tuples after streaming download, or [] if the
    user hasn't triggered download yet.

    When the user clicks 'Analyze & generate' in the calling view, this
    helper is re-invoked; we pull the selected files from session state.
    """
    st.text_input(
        "Google Drive folder URL or ID",
        key="drive_folder_input",
        placeholder="https://drive.google.com/drive/folders/…",
        help="Share the folder with the service account email as Viewer — see SETUP.md.",
    )

    cols = st.columns([1, 3])
    with cols[0]:
        scan = st.button("Scan folder", use_container_width=True, disabled=not st.session_state.drive_folder_input.strip())
    if scan:
        try:
            creds = _drive_creds()
            from src.drive import scan_folder
            with st.spinner("Listing Drive folder…"):
                result = scan_folder(st.session_state.drive_folder_input.strip(), recursive=True, creds=creds)
            st.session_state.drive_scan = {
                "folder_id": result.folder_id,
                "folder_name": result.folder_name,
                "files": result.files,
                "total_size_bytes": result.total_size_bytes,
                "counts": {
                    "total": len(result.files),
                    "supported": sum(1 for f in result.files if f["kind"] == "supported"),
                    "cad": sum(1 for f in result.files if f["kind"] == "cad"),
                    "media": sum(1 for f in result.files if f["kind"] == "media"),
                    "archive": sum(1 for f in result.files if f["kind"] == "archive"),
                    "other": sum(1 for f in result.files if f["kind"] == "other"),
                    "skipped": sum(1 for f in result.files if f["kind"] == "skipped"),
                },
            }
            st.session_state.drive_selected = set(
                f["id"] for f in result.files if f["kind"] == "supported"
            )
        except Exception as e:
            st.error(f"Scan failed: {e}")
            st.session_state.drive_scan = None

    scan = st.session_state.drive_scan
    if not scan:
        return []

    c = scan["counts"]
    st.markdown(
        f"**{scan['folder_name'] or scan['folder_id']}** · {c['total']} items · "
        f"{c['supported']} supported, {c['cad']} CAD, {c['media']} media, "
        f"{c['archive']} archive, {c['skipped']} unsupported · "
        f"{_format_bytes(scan['total_size_bytes'])}"
    )

    # Selection controls
    sel_cols = st.columns(3)
    if sel_cols[0].button("Select supported only"):
        st.session_state.drive_selected = set(f["id"] for f in scan["files"] if f["kind"] == "supported")
    if sel_cols[1].button("Select all non-skipped"):
        st.session_state.drive_selected = set(f["id"] for f in scan["files"] if f["kind"] != "skipped")
    if sel_cols[2].button("Deselect all"):
        st.session_state.drive_selected = set()

    # File tree (grouped by path)
    from collections import defaultdict
    by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in scan["files"]:
        by_folder[f["path"] or "(root)"].append(f)

    selected = st.session_state.drive_selected
    with st.container(border=True):
        for folder, entries in sorted(by_folder.items()):
            st.markdown(f"**{folder}**")
            for f in entries:
                disabled = f["kind"] == "skipped"
                checked = f["id"] in selected
                new_checked = st.checkbox(
                    f"`{f['kind']}`  {f['name']}  — {_format_bytes(f['size_bytes'])}",
                    value=checked, key=f"drive_sel_{f['id']}", disabled=disabled,
                )
                if new_checked != checked:
                    if new_checked: selected.add(f["id"])
                    else: selected.discard(f["id"])
                    st.session_state.drive_selected = selected

    # Cost preview
    selected_files = [f for f in scan["files"] if f["id"] in selected]
    est_in = sum(int(f.get("est_tokens") or 0) for f in selected_files)
    est_out = max(3000, 3000 * ((len(selected_files) // 25) + 1))
    cost = _estimate_cost(est_in, est_out)
    total_bytes = sum(int(f.get("size_bytes") or 0) for f in selected_files)

    mcols = st.columns(4)
    mcols[0].metric("Selected", f"{len(selected_files)}")
    mcols[1].metric("Size", _format_bytes(total_bytes))
    mcols[2].metric("Est. tokens in", _format_tokens(est_in))
    mcols[3].metric("Est. cost", f"${cost['total_cost']:.2f}")
    if cost["total_cost"] > 5:
        st.warning(f"Estimated cost is ~${cost['total_cost']:.2f}, over the $5 guardrail. Review selection before submitting.")

    # Files are not downloaded here — the caller triggers streaming on submit.
    return selected_files  # returns metadata, caller streams downloads


def view_create() -> None:
    st.markdown("# Create New Estimate")
    if st.button("← Back"):
        _goto("landing")

    key = _get_api_key()
    if not key:
        st.error("ANTHROPIC_API_KEY is not configured. Set it in the app's Secrets panel and reboot.")
        return

    # Project metadata
    st.markdown("### 1. Project details")
    c1, c2 = st.columns(2)
    name = c1.text_input("Project name", value=st.session_state.meta.get("name", ""))
    location = c2.text_input("Location (city, state)", value=st.session_state.meta.get("location", ""))
    c3, c4 = st.columns(2)
    client = c3.text_input("Client / GC", value=st.session_state.meta.get("client", ""))
    bid_due = c4.date_input(
        "Bid due date",
        value=st.session_state.meta.get("bid_due_date_obj") or _dt.date.today() + _dt.timedelta(days=7),
    )
    scope_hint = st.selectbox(
        "Expected scope (optional — leave blank to let Claude detect)",
        options=["", "Micropile", "Soil Nail", "HDPR", "Pre-drilling", "Shotcrete", "Soldier Pile", "Mixed", "Other"],
        index=0,
    )
    notes = st.text_area(
        "Notes / assumptions / exclusions (optional)",
        value=st.session_state.meta.get("notes", ""),
        height=100,
        help="Anything you want Claude to factor in that isn't in the uploaded files.",
    )

    # Source files — mode toggle
    st.markdown("### 2. Source files")
    drive_tab, upload_tab = st.tabs(["Google Drive folder", "Direct upload"])

    selected_drive_files: list[dict[str, Any]] = []
    uploaded = []
    with drive_tab:
        selected_drive_files = _render_drive_tab(key)
    with upload_tab:
        st.caption(
            "Drag and drop (or click to browse). Supported: PDF, DOCX, XLSX/XLS/CSV, PNG/JPG, TXT. "
            "For bid packages over ~1 GB, use the Drive tab."
        )
        uploaded = st.file_uploader(
            "Drop files here", type=None, accept_multiple_files=True, label_visibility="collapsed",
        )

    # Manual entries
    st.markdown("### 3. Manual entries (items not in the files)")
    manual_notes = st.text_area(
        "Manual quantities, rates, or context",
        value=st.session_state.manual_notes, height=120,
        placeholder="e.g., 'Client verbally confirmed 42 piles at 80ft each'\n"
                    "or 'Use $48/LF as baseline for 9-5/8\" casing based on last Enbridge quote'",
    )

    can_submit = bool(uploaded) or bool(selected_drive_files) or manual_notes.strip() or notes.strip()
    submitted = st.button("🚀  Analyze & Generate", type="primary", use_container_width=True, disabled=not can_submit)

    if submitted:
        meta = {
            "name": name, "location": location, "client": client,
            "bid_due_date": bid_due.isoformat() if bid_due else "",
            "bid_due_date_obj": bid_due,
            "scope_hint": scope_hint, "notes": notes,
        }
        st.session_state.meta = meta
        st.session_state.manual_notes = manual_notes

        uploaded_bytes = [(f.name, f.getvalue()) for f in (uploaded or [])]
        _run_analysis(meta, manual_notes, uploaded_bytes, selected_drive_files, key)


def _run_analysis(
    meta: dict[str, Any],
    manual_notes: str,
    uploaded: list[tuple[str, bytes]],
    drive_selection: list[dict[str, Any]],
    api_key: str,
) -> None:
    status = st.status("Analyzing bid package…", expanded=True)
    try:
        status.write(f"📥 Uploaded files: {len(uploaded)}")
        t0 = time.time()
        ingested = ingest_many(uploaded)
        for f in ingested:
            status.write(f"   • {f.text_summary}")

        if drive_selection:
            status.write(f"☁️ Streaming {len(drive_selection)} files from Google Drive…")
            creds = _drive_creds()
            from src.drive import download_one, _build_service
            service = _build_service(creds)
            progress = st.progress(0.0)
            for i, f in enumerate(drive_selection, start=1):
                status.write(f"   → {i}/{len(drive_selection)}  {f['name']}")
                try:
                    display_name, data = download_one(f, service=service)
                    one = ingest_file(display_name, data)
                    del data
                    ingested.append(one)
                    status.write(f"     {one.text_summary}")
                except Exception as e:
                    status.write(f"     ! error on {f['name']}: {e}")
                progress.progress(i / len(drive_selection))
            progress.empty()

        if not ingested and not manual_notes.strip() and not meta.get("notes", "").strip():
            raise RuntimeError("No files processed and no manual notes — nothing to analyze.")

        est_in = estimate_ingested_tokens(ingested)
        status.write(f"📊 Estimated input: ~{_format_tokens(est_in)} tokens across {len(ingested)} files")

        # --- Vision preprocess on plan-sheet PDFs (Phase 1 + Phase 2) ---
        # Collect the raw PDF bytes of every uploaded/Drive file, then filter
        # to plan-sheet-looking PDFs. Text-heavy specs are skipped — their
        # dimensions live in tables, not drawings.
        all_raw_pdfs = [(name, data) for name, data in uploaded
                        if name.lower().endswith(".pdf")]
        # Drive-pulled files already went through ingest_file directly; we
        # still have their bytes via the download loop above — skip those
        # here to keep the vision pipeline as an upload-time helper.
        plan_sheet_pdfs = filter_plan_sheet_pdfs(all_raw_pdfs)
        vision_data = None
        if plan_sheet_pdfs:
            status.write(f"🔍 Running vision pipeline on {len(plan_sheet_pdfs)} plan-sheet PDF(s)…")
            try:
                vision_data = run_vision_pipeline(plan_sheet_pdfs, api_key=api_key, model=_get_model())
                page_ct = sum(len(v.get("pages") or []) for v in vision_data)
                status.write(f"   ✅ Vision extracted {page_ct} page(s) of structured data")
            except Exception as e:
                status.write(f"   ⚠️ Vision pipeline failed: {e} — continuing without it")
                vision_data = None

        status.write(f"📤 Calling Claude ({_get_model()})…")
        t1 = time.time()

        def _on_batch(i: int, total: int, usage: dict[str, Any] | None) -> None:
            if total > 1:
                status.write(f"   • Claude batch {i}/{total} done "
                             f"({(usage or {}).get('input_tokens', 0)} in / "
                             f"{(usage or {}).get('output_tokens', 0)} out)")

        analysis = analyze_batched(
            meta, manual_notes, ingested,
            api_key=api_key, model=_get_model(), on_batch=_on_batch,
            vision_data=vision_data,
        )
        t2 = time.time()
        usage = (analysis.get("_meta") or {}).get("usage") or {"input_tokens": 0, "output_tokens": 0}
        batches = (analysis.get("_meta") or {}).get("batches", 1)
        cost = _estimate_cost(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
        status.write(
            f"   ✅ Claude done in {t2-t1:.1f}s across {batches} "
            f"batch{'es' if batches != 1 else ''}  "
            f"(in: {usage['input_tokens']} tok, out: {usage['output_tokens']} tok, "
            f"cost ~${cost['total_cost']:.2f})"
        )

        status.write("📝 Building outputs…")
        outputs = {
            "01_Takeoff.xlsx": build_takeoff_xlsx(analysis),
            "02_Project_Info.docx": build_project_info_docx(analysis),
            "03_Vendor_RFQs.docx": build_vendor_rfqs_docx(analysis),
            "04_Cost_Proposal.docx": build_proposal_docx(analysis),
        }
        for name in outputs:
            status.write(f"   ✅ {name} ({len(outputs[name])/1024:.0f} KB)")

        st.session_state.analysis = analysis
        st.session_state.outputs = outputs
        status.update(label=f"✅ Done in {time.time()-t0:.1f}s", state="complete")
        _goto("results")
    except Exception as e:
        status.update(label=f"❌ {e}", state="error")
        st.session_state.error = str(e)
        st.exception(e)


def view_results() -> None:
    analysis = st.session_state.analysis
    outputs = st.session_state.outputs
    if not analysis or not outputs:
        _goto("landing")
        return

    project = analysis.get("project") or {}
    st.markdown(f"# {project.get('name') or 'Unnamed Project'}")
    st.caption(f"{project.get('location', '')} · {project.get('client', '')} · "
               f"Scope: {project.get('scope_type', '')} · Bid due: {project.get('bid_due_date', '')}")

    if st.button("← New estimate"):
        st.session_state.analysis = None
        st.session_state.outputs = None
        _goto("create")

    st.markdown("## 📦 Download outputs")
    cols = st.columns(4)
    for i, (name, data) in enumerate(outputs.items()):
        with cols[i]:
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") \
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            st.download_button(
                label=f"⬇️  {name}",
                data=data,
                file_name=name,
                mime=mime,
                use_container_width=True,
            )

    st.markdown("## 🔎 Preview")
    tabs = st.tabs(["Scope", "Takeoff", "Testing", "Design", "Unknowns", "Risks", "Equipment", "Vendors", "Raw JSON"])

    with tabs[0]:
        st.write(f"**Description:** {project.get('description', '')}")
        st.write(f"**Site conditions:** {project.get('site_conditions', '')}")
        st.write(f"**Schedule:** {project.get('schedule_notes', '')}")
        st.write(f"**Files ingested:** {len(analysis.get('file_appendix') or [])}")
        if analysis.get("file_appendix"):
            st.dataframe(analysis["file_appendix"], use_container_width=True)

    with tabs[1]:
        items = analysis.get("takeoff_items") or []
        st.write(f"{len(items)} item(s)")
        if items: st.dataframe(items, use_container_width=True)

    with tabs[2]:
        tests = analysis.get("testing_requirements") or []
        st.write(f"{len(tests)} test(s)")
        if tests: st.dataframe(tests, use_container_width=True)

    with tabs[3]:
        st.json(analysis.get("design_requirements") or {})

    with tabs[4]:
        ua = analysis.get("unknowns_and_assumptions") or []
        st.write(f"{len(ua)} item(s)")
        if ua: st.dataframe(ua, use_container_width=True)

    with tabs[5]:
        risks = analysis.get("estimating_risks") or []
        st.write(f"{len(risks)} risk(s)")
        if risks: st.dataframe(risks, use_container_width=True)

    with tabs[6]:
        eq = analysis.get("equipment_list") or []
        st.write(f"{len(eq)} piece(s)")
        if eq: st.dataframe(eq, use_container_width=True)

    with tabs[7]:
        vendors = analysis.get("vendor_list") or []
        st.write(f"{len(vendors)} vendor categor(ies)")
        for v in vendors:
            with st.expander(f"🏷️ {v.get('vendor_category', '')}"):
                st.write("Suggested vendors:", ", ".join(v.get("suggested_vendors") or []))
                st.write("Takeoff items:")
                st.dataframe(v.get("takeoff_items_for_rfq") or [], use_container_width=True)
                if v.get("testing_items_for_rfq"):
                    st.write("Testing items:", v["testing_items_for_rfq"])

    with tabs[8]:
        st.json(analysis)


# --- Router ---------------------------------------------------------------------

VIEWS = {"landing": view_landing, "create": view_create, "results": view_results}
VIEWS[st.session_state.view]()
