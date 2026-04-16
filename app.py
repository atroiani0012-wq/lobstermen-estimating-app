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
import pathlib as _pathlib
import subprocess as _subprocess
import time
from typing import Any

import streamlit as st

from src.ingest import ingest_many
from src.analyze import analyze, DEFAULT_MODEL
from src.outputs.takeoff import build_takeoff_xlsx
from src.outputs.project_info import build_project_info_docx
from src.outputs.vendor_rfqs import build_vendor_rfqs_docx
from src.outputs.proposal import build_proposal_docx
from src.outputs.bidder_list import build_bidder_list_xlsx
from src.drive_pull import pull_folder, DEFAULT_SKIP_FOLDER_NAMES


# --- Deployed build fingerprint --------------------------------------------------
# Captured at import time so the Streamlit admin / smoke tests can confirm
# which commit is actually live without logging into the app.
def _read_deployed_sha() -> str:
    # 1. Streamlit Cloud exposes the commit SHA via env var during builds.
    for var in ("STREAMLIT_COMMIT_SHA", "GIT_COMMIT", "RENDER_GIT_COMMIT"):
        val = os.environ.get(var)
        if val:
            return val[:12]
    # 2. Local dev / generic container: ask git if the repo is there.
    try:
        root = _pathlib.Path(__file__).resolve().parent
        out = _subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            stderr=_subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode().strip()
    except Exception:
        pass
    return "unknown"


DEPLOYED_SHA = _read_deployed_sha()


# --- Runtime budget constants ----------------------------------------------------

MAX_ANALYSIS_SECONDS = 30 * 60  # 30 minutes — per Tony's rule
WARN_THRESHOLD_SECONDS = MAX_ANALYSIS_SECONDS * 0.8  # warn at 80% burn

# Rough ETA model (seconds):
#   ingest: ~3s per file + ~0.5s per MB of PDF
#   claude analyze (no web search): ~45s baseline + 15s per 10 files
#   web search: ~8s per search, up to 15
#   output build: ~3s total
def _estimate_runtime(num_files: int, total_mb: float, web_enabled: bool) -> float:
    ingest = 3 * num_files + 0.5 * total_mb
    analyze = 45 + 15 * (num_files / 10)
    web = (8 * 15) if web_enabled else 0
    build = 3
    return ingest + analyze + web + build


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
            "- **First-draft Cost Proposal** (.docx)\n"
            "- **Prospective Bidder List** (.xlsx) — companies that requested bid docs, pulled from web research"
        )

    with st.expander("System status"):
        key = _get_api_key()
        st.write("**Anthropic API key:**", "✅ configured" if key else "❌ missing — set ANTHROPIC_API_KEY in secrets")
        st.write("**Model:**", _get_model())
        st.write("**Max upload size:**", "1 GB per file")
        st.write("**Web research:**", "enabled (max 15 searches)")
        st.write("**Max analysis runtime:**", "30 minutes")
        st.write("**Deployed build:**", f"`{DEPLOYED_SHA}`")


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

        st.markdown("### 2. Pull files from Google Drive (recommended)")
        st.caption(
            "Paste the project folder URL. Backend pulls every file recursively, "
            f"auto-skipping: {', '.join(sorted(DEFAULT_SKIP_FOLDER_NAMES))}. "
            "Grant the service account Viewer access on the folder first."
        )
        drive_url = st.text_input(
            "Google Drive folder URL or ID",
            value="",
            placeholder="https://drive.google.com/drive/folders/1abc...XYZ",
            label_visibility="collapsed",
        )

        st.markdown("### 2b. Or drop files directly")
        st.caption(
            "Drag and drop (or click to browse). Supported: PDF, DOCX, XLSX/XLS/CSV, PNG/JPG, TXT. "
            "Up to 1 GB per file."
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
        if not uploaded and not drive_url.strip() and not manual_notes.strip() and not notes.strip():
            st.error("Paste a Drive folder URL, upload files, or enter manual notes before analyzing.")
            return

        meta = {
            "name": name, "location": location, "client": client,
            "bid_due_date": bid_due.isoformat() if bid_due else "",
            "bid_due_date_obj": bid_due,
            "scope_hint": scope_hint, "notes": notes,
        }
        st.session_state.meta = meta
        st.session_state.manual_notes = manual_notes

        file_tuples: list[tuple[str, bytes]] = []

        # Pull from Drive first (typically the bulk of the files)
        if drive_url.strip():
            pull_status = st.status("📂 Pulling files from Google Drive…", expanded=True)
            try:
                def _cb(msg: str) -> None:
                    pull_status.write(msg)
                result = pull_folder(drive_url.strip(), progress_cb=_cb)
                pull_status.write(
                    f"✅ {len(result.files)} file(s), "
                    f"{result.total_bytes/1024/1024:.1f} MB total"
                )
                if result.skipped_folders:
                    pull_status.write(
                        f"   Skipped folders: {', '.join(result.skipped_folders)}"
                    )
                if result.skipped_files:
                    pull_status.write(
                        f"   Skipped files: {len(result.skipped_files)} "
                        f"(e.g. {result.skipped_files[0] if result.skipped_files else ''})"
                    )
                if result.errors:
                    for err in result.errors[:5]:
                        pull_status.write(f"   ⚠ {err}")
                pull_status.update(state="complete")
                file_tuples.extend(result.files)
            except Exception as e:
                pull_status.update(label=f"❌ Drive pull failed: {e}", state="error")
                st.exception(e)
                return

        # Then append any manually-uploaded files
        file_tuples.extend((f.name, f.getvalue()) for f in (uploaded or []))

        if not file_tuples and not manual_notes.strip() and not notes.strip():
            st.error("No files pulled or uploaded, and no manual notes — nothing to analyze.")
            return

        _run_analysis(meta, manual_notes, file_tuples, key)


def _run_analysis(meta: dict[str, Any], manual_notes: str, file_tuples: list[tuple[str, bytes]], api_key: str) -> None:
    # Pre-flight estimate
    total_mb = sum(len(data) for _, data in file_tuples) / 1024 / 1024
    est_secs = _estimate_runtime(len(file_tuples), total_mb, web_enabled=True)
    est_mins = est_secs / 60

    st.info(f"📊 Estimated analysis time: ~{est_mins:.1f} minutes")

    # 30-min ceiling warning
    if est_secs > WARN_THRESHOLD_SECONDS:
        st.warning(
            f"⚠️  This estimate ({est_mins:.1f} min) exceeds our 80% safety margin "
            f"(24 min). Full analysis may run close to 30 min. "
            "Proceed only if you're comfortable with potential delays."
        )
        proceed_anyway_key = "proceed_anyway_large_analysis"
        if proceed_anyway_key not in st.session_state:
            st.session_state[proceed_anyway_key] = False
        st.session_state[proceed_anyway_key] = st.checkbox(
            "Proceed anyway — I understand this may run over 30 min"
        )
        if not st.session_state[proceed_anyway_key]:
            st.stop()

    status = st.status("Analyzing bid package…", expanded=True)
    t_start = time.time()

    try:
        # Ingest phase
        status.write(f"📥 Ingesting {len(file_tuples)} file(s)…")
        t_ingest_start = time.perf_counter()
        ingested = ingest_many(file_tuples)
        for f in ingested:
            status.write(f"   • {f.text_summary}")
        t_ingest_end = time.perf_counter()
        ingest_elapsed = t_ingest_end - t_ingest_start

        # Analyze phase
        status.write(f"📤 Calling Claude ({_get_model()})…")
        t_analyze_start = time.perf_counter()

        def _progress_cb(msg: str) -> None:
            elapsed_total = time.perf_counter() - t_analyze_start
            remaining_budget = MAX_ANALYSIS_SECONDS - (time.time() - t_start)
            eta_str = f"{remaining_budget/60:.1f}m" if remaining_budget > 0 else "⏱️ over"
            status.write(f"{msg} · Elapsed {elapsed_total:.0f}s, ETA {eta_str} (analyze)")

        analysis = analyze(
            meta, manual_notes, ingested, api_key=api_key, model=_get_model(),
            progress_cb=_progress_cb
        )
        t_analyze_end = time.perf_counter()
        analyze_elapsed = t_analyze_end - t_analyze_start

        status.write(f"   ✅ Claude done in {analyze_elapsed:.1f}s "
                     f"(in: {analysis['_meta']['usage']['input_tokens']} tok, "
                     f"out: {analysis['_meta']['usage']['output_tokens']} tok)")

        # Check hard ceiling before output build
        if time.time() - t_start > MAX_ANALYSIS_SECONDS:
            status.write(f"⚠️  ⏱️  EXCEEDED 30-MIN BUDGET by {(time.time()-t_start-MAX_ANALYSIS_SECONDS)/60:.1f} min. "
                         "Proceeding to output generation anyway.")

        # Build outputs phase
        status.write("📝 Building outputs…")
        t_build_start = time.perf_counter()
        outputs = {
            "01_Takeoff.xlsx": build_takeoff_xlsx(analysis),
            "02_Project_Info.docx": build_project_info_docx(analysis),
            "03_Vendor_RFQs.docx": build_vendor_rfqs_docx(analysis),
            "04_Cost_Proposal.docx": build_proposal_docx(analysis),
        }
        # Conditionally add 5th output
        if analysis.get("web_research", {}).get("bidder_list"):
            outputs["05_Bidder_List.xlsx"] = build_bidder_list_xlsx(analysis)
        for name in outputs:
            status.write(f"   ✅ {name} ({len(outputs[name])/1024:.0f} KB)")
        t_build_end = time.perf_counter()
        build_elapsed = t_build_end - t_build_start

        total_elapsed = time.time() - t_start
        st.session_state.analysis = analysis
        st.session_state.outputs = outputs
        status.update(label=f"✅ Done in {total_elapsed:.1f}s "
                           f"(ingest {ingest_elapsed:.1f}s, analyze {analyze_elapsed:.1f}s, build {build_elapsed:.1f}s)",
                     state="complete")
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
    num_outputs = len(outputs)
    cols = st.columns(num_outputs if num_outputs == 5 else 4)
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
    tabs = st.tabs(["Scope", "Takeoff", "Testing", "Design", "Unknowns", "Risks", "Equipment", "Vendors", "🌐 Research", "Raw JSON"])

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
        wr = analysis.get("web_research", {})
        st.write("**Project metadata (from web research)**")
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Owner/Grantee:**", wr.get("owner_confirmed", "(not found)"))
            st.write("**EOR (Engineer of Record):**", wr.get("eor", "(not found)"))
        with col2:
            st.write("**Budget/Award Value:**", wr.get("budget_or_award_value", "(not found)"))

        st.write("")
        st.write("**Prospective bidders list**")
        bidders = wr.get("bidder_list") or []
        if bidders:
            st.dataframe(bidders, use_container_width=True)
        else:
            st.write("(no bidders found)")

        st.write("")
        st.write("**Research findings**")
        findings = wr.get("findings") or []
        if findings:
            st.dataframe(findings, use_container_width=True)
        else:
            st.write("(no additional findings)")

        st.caption(f"Searches attempted: {analysis.get('_meta', {}).get('web_searches_run', 0)}")

    with tabs[9]:
        st.json(analysis)


# --- Router ---------------------------------------------------------------------

# Lightweight "version" view: hit the app with ?v=1 to see the deployed SHA
# as plain text in the page header — useful for smoke-testing from a browser
# without clicking through the UI. Bypasses login redirect once authenticated.
_qp = st.query_params
if _qp.get("v") == "1" or _qp.get("version") == "1":
    st.markdown(f"## Deployed build: `{DEPLOYED_SHA}`")
    st.caption(f"Built at import time from environment (Streamlit Cloud sets STREAMLIT_COMMIT_SHA).")
    st.stop()

VIEWS = {"landing": view_landing, "create": view_create, "results": view_results}
VIEWS[st.session_state.view]()
