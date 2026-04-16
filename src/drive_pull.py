"""
Google Drive folder pull.

Given a Drive folder URL (or raw folder ID), recursively download every file
inside — skipping known "answer" subfolders (Estimates, Proposals, Follow Up,
Correspondence) by default — and return them as (filename, bytes) tuples in
the same shape that `ingest_many` expects.

Auth: service-account JSON stored in st.secrets["GDRIVE_SERVICE_ACCOUNT"] (or
env var GDRIVE_SERVICE_ACCOUNT as a JSON string). The service account must
have viewer access to the folder (share the folder with the service account
email).

Workspace docs (Google Docs/Sheets/Slides) are exported to PDF/XLSX/PPTX so
they flow into the existing ingest pipeline.
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from typing import Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# Subfolder names (case-insensitive) to skip when pulling a project folder.
# These contain answer / post-award artifacts that would contaminate an estimate.
DEFAULT_SKIP_FOLDER_NAMES = {
    "estimates",
    "proposals",
    "follow up",
    "follow-up",
    "followup",
    "correspondence",
}

# Max total bytes across a single pull. 2 GB ceiling keeps the Streamlit app
# from OOM'ing on accidentally-huge folders.
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

# Per-file ceiling — matches Streamlit's 1 GB uploader cap so downstream ingest
# code has parity.
MAX_PER_FILE_BYTES = 1 * 1024 * 1024 * 1024

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Export map for native Google Workspace mimetypes → downloadable formats.
GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

# Shortcuts: resolve via shortcutDetails.targetId + targetMimeType.


@dataclass
class PullResult:
    files: list[tuple[str, bytes]]
    total_bytes: int
    skipped_folders: list[str]
    skipped_files: list[str]  # name + reason
    errors: list[str]


_FOLDER_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_\-]+)")


def extract_folder_id(url_or_id: str) -> str:
    """Accepts a full Drive URL, a `?id=...`, or a bare folder ID."""
    url_or_id = (url_or_id or "").strip()
    if not url_or_id:
        raise ValueError("Empty Drive folder URL / ID")
    m = _FOLDER_ID_RE.search(url_or_id)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_\-]+)", url_or_id)
    if m:
        return m.group(1)
    # Bare ID fallback — Drive IDs are typically 25+ chars alphanumeric/-/_
    if re.fullmatch(r"[a-zA-Z0-9_\-]{20,}", url_or_id):
        return url_or_id
    raise ValueError(f"Could not parse Drive folder ID from: {url_or_id!r}")


def _load_service_account_info() -> dict:
    """Load SA creds from Streamlit secrets or env var. Returns parsed dict."""
    raw = None
    try:
        import streamlit as st  # local import — module works outside Streamlit too
        sa = st.secrets.get("GDRIVE_SERVICE_ACCOUNT")
        if sa is not None:
            # st.secrets supports nested TOML tables; accept dict or JSON string
            if isinstance(sa, dict):
                return dict(sa)
            raw = str(sa)
    except Exception:
        pass

    if raw is None:
        raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
    if raw is None:
        raise RuntimeError(
            "GDRIVE_SERVICE_ACCOUNT not set. Add the service-account JSON to "
            "Streamlit Secrets (key: GDRIVE_SERVICE_ACCOUNT) or as an env var."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GDRIVE_SERVICE_ACCOUNT is not valid JSON: {e}") from e


def _build_drive_service():
    info = _load_service_account_info()
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_children(service, folder_id: str) -> list[dict]:
    """Return all direct children of a folder (files + subfolders), paginated."""
    out: list[dict] = []
    page_token = None
    q = f"'{folder_id}' in parents and trashed = false"
    fields = (
        "nextPageToken, files(id, name, mimeType, size, "
        "shortcutDetails(targetId, targetMimeType))"
    )
    while True:
        resp = service.files().list(
            q=q,
            fields=fields,
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def _download_file(service, file_id: str, mime_type: str, name: str) -> tuple[bytes, str]:
    """Download a file; return (bytes, final_filename). Handles Workspace exports."""
    if mime_type in GOOGLE_EXPORT_MAP:
        export_mime, ext = GOOGLE_EXPORT_MAP[mime_type]
        req = service.files().export_media(fileId=file_id, mimeType=export_mime)
        final_name = name if name.lower().endswith(ext) else f"{name}{ext}"
    else:
        req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        final_name = name

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req, chunksize=10 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue(), final_name


def pull_folder(
    folder_url_or_id: str,
    skip_folder_names: Iterable[str] | None = None,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_per_file_bytes: int = MAX_PER_FILE_BYTES,
    progress_cb=None,
) -> PullResult:
    """
    Pull every file from `folder_url_or_id` recursively.

    progress_cb(msg: str) — optional callback for UI updates.
    """
    skip_set = {s.lower() for s in (skip_folder_names or DEFAULT_SKIP_FOLDER_NAMES)}
    root_id = extract_folder_id(folder_url_or_id)

    service = _build_drive_service()
    files_out: list[tuple[str, bytes]] = []
    skipped_folders: list[str] = []
    skipped_files: list[str] = []
    errors: list[str] = []
    total = 0

    def _emit(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    # BFS over folders so the UI can stream progress
    queue: list[tuple[str, str]] = [(root_id, "")]  # (folder_id, relative_path)
    visited: set[str] = set()

    while queue:
        folder_id, rel_path = queue.pop(0)
        if folder_id in visited:
            continue
        visited.add(folder_id)

        try:
            children = _list_children(service, folder_id)
        except Exception as e:
            errors.append(f"List {rel_path or '/'}: {e}")
            continue

        for item in children:
            name = item.get("name", "")
            mime = item.get("mimeType", "")
            file_id = item.get("id")

            # Resolve shortcuts
            if mime == "application/vnd.google-apps.shortcut":
                details = item.get("shortcutDetails") or {}
                tgt_id = details.get("targetId")
                tgt_mime = details.get("targetMimeType")
                if not tgt_id:
                    skipped_files.append(f"{name} (broken shortcut)")
                    continue
                file_id = tgt_id
                mime = tgt_mime or ""

            child_path = f"{rel_path}/{name}" if rel_path else name

            if mime == "application/vnd.google-apps.folder":
                if name.lower() in skip_set:
                    skipped_folders.append(child_path)
                    _emit(f"⏭ skip folder {child_path}")
                    continue
                queue.append((file_id, child_path))
                continue

            # Regular file
            size_str = item.get("size")
            size = int(size_str) if size_str else 0
            if size and size > max_per_file_bytes:
                skipped_files.append(f"{child_path} (>{max_per_file_bytes // (1024*1024)} MB)")
                _emit(f"⏭ skip {child_path} — too large")
                continue
            if size and total + size > max_total_bytes:
                skipped_files.append(f"{child_path} (total cap exceeded)")
                _emit(f"⏭ skip {child_path} — total cap hit")
                continue

            try:
                _emit(f"⬇ {child_path}")
                data, final_name = _download_file(service, file_id, mime, name)
                total += len(data)
                # Prefix with relative path to keep uniqueness across subfolders
                unique_name = final_name if not rel_path else f"{rel_path}__{final_name}".replace("/", "_")
                files_out.append((unique_name, data))
            except Exception as e:
                errors.append(f"Download {child_path}: {e}")
                skipped_files.append(f"{child_path} (download error)")

    return PullResult(
        files=files_out,
        total_bytes=total,
        skipped_folders=skipped_folders,
        skipped_files=skipped_files,
        errors=errors,
    )
