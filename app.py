"""
Lobstermen Estimating App — Streamlit entry point.

Flow:
  1. Landing → "Create New Estimate"
  2. Create Estimate page: project metadata + drag-drop files + manual notes
  3. Analyze & Generate → Claude call → 4 downloadable outputs
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import time
from typing import Any

import streamlit as st

from src.ingest import ingest_many
from src.analyze import analyze, DEFAULT_MODEL
from src.outputs.takeoff import build_takeoff_xlsx
from src.outputs.project_info import build_project_info_docx
from src.outputs.vendor_rfqs import build_vendor_rfqs_docx
from src.outputs.proposal import build_proposal_docx


# --- Page config ----------------------------------------------------------------

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
]:
    if key not in st.session_state:
        st.session_state[key] = default


def _goto(view: str) -> None:
    st.session_state.view = view
    st.rerun()


def _get_api_key() -> str | None:
    # Streamlit Cloud: secrets.toml. Local dev: env var also accepted.
    key = None
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        pass
    return key or os.environ.get("ANTHROPIC_API_KEY")


def _get_model() -> str:
    try:
        m = st.secrets.get("ANTHROPIC_MODEL")
        if m:
            return m
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


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
        st.write("**Max upload size:**", "1 GB per file")


def view_create() -> None:
    st.markdown("# Create New Estimate")
    if st.button("← Back"):
        _goto("landing")

    key = _get_api_key()
    if not key:
        st.error("ANTHROPIC_API_KEY is not configured. Set it in the app's Secrets panel and reboot.")
        return

    with st.form("estimate_form", clear_on_submit=False):
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

        st.markdown("### 2. Drop bid-package files")
        st.caption(
            "Drag and drop (or click to browse). Supported: PDF, DOCX, XLSX/XLS/CSV, PNG/JPG, TXT. "
            "Up to 1 GB per file. Drop everything — drawings, specs, geotech, RFQs, photos."
        )
        uploaded = st.file_uploader(
            "Drop files here",
            type=None,
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        st.markdown("### 3. Manual entries (items not in the files)")
        manual_notes = st.text_area(
            "Manual quantities, rates, or context",
            value=st.session_state.manual_notes,
            height=120,
            placeholder="e.g., 'Client verbally confirmed 42 piles at 80ft each'\n"
                        "or 'Use $48/LF as baseline for 9-5/8\" casing based on last Enbridge quote'",
        )

        submitted = st.form_submit_button("🚀  Analyze & Generate", type="primary", use_container_width=True)

    if submitted:
        if not uploaded and not manual_notes.strip() and not notes.strip():
            st.error("Upload at least one file or enter manual notes before analyzing.")
            return

        meta = {
            "name": name, "location": location, "client": client,
            "bid_due_date": bid_due.isoformat() if bid_due else "",
            "bid_due_date_obj": bid_due,
            "scope_hint": scope_hint, "notes": notes,
        }
        st.session_state.meta = meta
        st.session_state.manual_notes = manual_notes

        file_tuples = [(f.name, f.getvalue()) for f in (uploaded or [])]
        _run_analysis(meta, manual_notes, file_tuples, key)


def _run_analysis(meta: dict[str, Any], manual_notes: str, file_tuples: list[tuple[str, bytes]], api_key: str) -> None:
    status = st.status("Analyzing bid package…", expanded=True)
    try:
        status.write(f"📥 Ingesting {len(file_tuples)} file(s)…")
        t0 = time.time()
        ingested = ingest_many(file_tuples)
        for f in ingested:
            status.write(f"   • {f.text_summary}")
        status.write(f"📤 Calling Claude ({_get_model()})…")
        t1 = time.time()
        analysis = analyze(meta, manual_notes, ingested, api_key=api_key, model=_get_model())
        t2 = time.time()
        status.write(f"   ✅ Claude done in {t2-t1:.1f}s "
                     f"(in: {analysis['_meta']['usage']['input_tokens']} tok, "
                     f"out: {analysis['_meta']['usage']['output_tokens']} tok)")

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
        # Preserve meta but clear analysis
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
        if items:
            st.dataframe(items, use_container_width=True)

    with tabs[2]:
        tests = analysis.get("testing_requirements") or []
        st.write(f"{len(tests)} test(s)")
        if tests:
            st.dataframe(tests, use_container_width=True)

    with tabs[3]:
        st.json(analysis.get("design_requirements") or {})

    with tabs[4]:
        ua = analysis.get("unknowns_and_assumptions") or []
        st.write(f"{len(ua)} item(s)")
        if ua:
            st.dataframe(ua, use_container_width=True)

    with tabs[5]:
        risks = analysis.get("estimating_risks") or []
        st.write(f"{len(risks)} risk(s)")
        if risks:
            st.dataframe(risks, use_container_width=True)

    with tabs[6]:
        eq = analysis.get("equipment_list") or []
        st.write(f"{len(eq)} piece(s)")
        if eq:
            st.dataframe(eq, use_container_width=True)

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
