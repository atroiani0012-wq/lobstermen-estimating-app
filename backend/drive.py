"""Google Drive integration for large bid packages.

Typical bid packages (plan sets, geotech reports, CAD exports) run 5-10 GB —
too large for direct browser upload. Instead the user drops files into a
Google Drive folder and pastes the folder URL; this module downloads the
contents server-side.

Auth precedence:
  1. payload-level service-account JSON (string or dict) — useful for Tasklet
  2. GOOGLE_SERVICE_ACCOUNT_JSON env var (inline JSON string)
  3. GOOGLE_APPLICATION_CREDENTIALS env var (path to a JSON file)

The service account email must have at least Viewer access to the target
folder — share the folder with the service account's email the same way
you'd share with a teammate.

Public API:
  parse_folder_id(url_or_id: str) -> str
  list_folder(folder_id: str, recursive: bool = True, creds=None) -> list[DriveFile]
  download_file(file_id: str, creds=None) -> bytes
  download_folder_contents(
      url_or_id: str,
      recursive: bool = True,
      max_file_bytes: int | None = 250 * 1024 * 1024,
      max_total_bytes: int | None = 8 * 1024 * 1024 * 1024,
      skip_unsupported: bool = True,
      progress: Callable[[DriveProgress], None] | None = None,
      creds=None,
  ) -> DriveDownloadResult

Google-native files are exported to portable formats:
  - Docs        → .docx
  - Spreadsheets → .xlsx
  - Slides      → .pdf
Other Google-native types (forms, drawings) are skipped with a note.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# ---- File-type policy -------------------------------------------------------

# MIME types of regular (non-Google-native) files we accept downstream.
# Mirrors the ingest module's supported extensions: PDF, DOCX, XLSX/XLS/CSV,
# images, TXT. Anything else is passed through (ingest has a fallback block
# that notes unsupported files) — we don't pre-filter silently.
_SUPPORTED_REGULAR_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "application/vnd.ms-excel",                                                 # .xls
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/markdown",
}

# Map Google-native MIME types to the export MIME + the filename extension we
# append when the source title has no extension.
_GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

_FOLDER_MIME = "application/vnd.google-apps.folder"
_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


# ---- Data types -------------------------------------------------------------

@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size_bytes: int = 0
    path: str = ""            # slash-joined parent folder names within the scope
    google_native: bool = False
    export_mime: str | None = None
    export_ext: str | None = None
    skipped_reason: str | None = None


@dataclass
class DriveProgress:
    stage: str                # "listing" | "downloading"
    file_index: int = 0
    file_count: int = 0
    filename: str = ""
    bytes_downloaded: int = 0
    total_bytes: int = 0


@dataclass
class DriveDownloadResult:
    folder_id: str
    folder_name: str | None
    files: list[tuple[str, bytes]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0
    listed: int = 0


# ---- URL / ID parsing -------------------------------------------------------

_URL_PATTERNS = (
    re.compile(r"/folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"/drive/folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})"),
)
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def parse_folder_id(url_or_id: str) -> str:
    """Extract a Google Drive folder ID from a URL or return the raw ID."""
    if not url_or_id:
        raise ValueError("Drive folder URL/ID is empty.")
    s = url_or_id.strip()
    if _BARE_ID.match(s):
        return s
    for pat in _URL_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(1)
    raise ValueError(
        f"Could not parse a Drive folder ID from {url_or_id!r}. "
        "Paste either a bare folder ID or a URL like "
        "https://drive.google.com/drive/folders/<ID>"
    )


# ---- Credentials ------------------------------------------------------------

_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)


def _load_credentials(override: Any = None):
    """Load service-account credentials, raising a clear error if none are configured."""
    from google.oauth2 import service_account  # type: ignore

    info: dict[str, Any] | None = None

    if override is not None:
        if isinstance(override, dict):
            info = override
        elif isinstance(override, str):
            info = json.loads(override)

    if info is None:
        env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if env_json:
            info = json.loads(env_json)

    if info is not None:
        return service_account.Credentials.from_service_account_info(info, scopes=list(_SCOPES))

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path:
        return service_account.Credentials.from_service_account_file(path, scopes=list(_SCOPES))

    raise RuntimeError(
        "No Google Drive credentials available. Set GOOGLE_SERVICE_ACCOUNT_JSON "
        "(inline JSON) or GOOGLE_APPLICATION_CREDENTIALS (path to a key file), "
        "or pass a `service_account` field in the payload. The service account "
        "must have Viewer access to the target folder."
    )


def _build_service(creds=None):
    from googleapiclient.discovery import build  # type: ignore
    creds = creds or _load_credentials()
    # cache_discovery=False avoids writing a discovery cache file that fails in read-only sandboxes.
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---- Listing ----------------------------------------------------------------

def _list_children(service, parent_id: str) -> Iterable[dict[str, Any]]:
    """Yield all immediate children of a folder (paginated)."""
    page_token: str | None = None
    fields = "nextPageToken, files(id, name, mimeType, size, shortcutDetails)"
    while True:
        resp = service.files().list(
            q=f"'{parent_id}' in parents and trashed = false",
            pageSize=1000,
            fields=fields,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for entry in resp.get("files", []):
            yield entry
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _classify(entry: dict[str, Any], path: str) -> DriveFile | None:
    """Turn a raw API entry into a DriveFile, or None if it's a folder to recurse."""
    mime = entry.get("mimeType", "")
    name = entry.get("name", "")
    fid = entry.get("id", "")
    size = int(entry.get("size") or 0)

    if mime == _FOLDER_MIME:
        return None

    if mime == _SHORTCUT_MIME:
        details = entry.get("shortcutDetails") or {}
        tgt_mime = details.get("targetMimeType", "")
        tgt_id = details.get("targetId")
        if not tgt_id:
            return DriveFile(id=fid, name=name, mime_type=mime, path=path,
                             skipped_reason="shortcut with no target")
        # Follow shortcut inline — use shortcut's display name with target mime.
        return _classify({"id": tgt_id, "name": name, "mimeType": tgt_mime, "size": entry.get("size")}, path)

    if mime in _GOOGLE_EXPORTS:
        export_mime, export_ext = _GOOGLE_EXPORTS[mime]
        out_name = name if pathlib.Path(name).suffix else name + export_ext
        return DriveFile(
            id=fid, name=out_name, mime_type=mime, size_bytes=size, path=path,
            google_native=True, export_mime=export_mime, export_ext=export_ext,
        )

    if mime.startswith("application/vnd.google-apps."):
        # Form, site, Jamboard, etc. — nothing exportable for our pipeline.
        return DriveFile(id=fid, name=name, mime_type=mime, size_bytes=size, path=path,
                         skipped_reason=f"unsupported Google-native type {mime}")

    return DriveFile(id=fid, name=name, mime_type=mime, size_bytes=size, path=path)


def _folder_name(service, folder_id: str) -> str | None:
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="name",
            supportsAllDrives=True,
        ).execute()
        return meta.get("name")
    except Exception:
        return None


def list_folder(
    folder_id: str,
    recursive: bool = True,
    creds=None,
    service=None,
) -> list[DriveFile]:
    """List files under a folder. Recurses into subfolders by default."""
    service = service or _build_service(creds)

    out: list[DriveFile] = []
    queue: list[tuple[str, str]] = [(folder_id, "")]
    visited: set[str] = set()

    while queue:
        parent, path = queue.pop(0)
        if parent in visited:
            continue
        visited.add(parent)
        for entry in _list_children(service, parent):
            if entry.get("mimeType") == _FOLDER_MIME:
                subpath = f"{path}/{entry.get('name', '')}".lstrip("/")
                if recursive:
                    queue.append((entry["id"], subpath))
                continue
            df = _classify(entry, path)
            if df is not None:
                out.append(df)
    return out


# ---- Download ---------------------------------------------------------------

def _unique_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        taken.add(name)
        return name
    stem = pathlib.Path(name).stem
    ext = pathlib.Path(name).suffix
    for i in range(2, 1000):
        candidate = f"{stem} ({i}){ext}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    taken.add(name)
    return name


def _download_regular(service, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload  # type: ignore
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buf.getvalue()


def _export_google(service, file_id: str, export_mime: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload  # type: ignore
    request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buf.getvalue()


def download_file(file_id: str, creds=None, service=None) -> bytes:
    """Download a regular (non-Google-native) Drive file by ID."""
    service = service or _build_service(creds)
    return _download_regular(service, file_id)


# ---- Scan (metadata-only listing with token/cost estimates) ---------------

# Rough per-file token estimate used to size Claude batches before we pay for
# the real tokenizer. Real rates (for context): Claude Sonnet charges a few
# thousand tokens per document-block PDF page. We bias slightly high so the
# batcher errs toward smaller batches.
_EST_TOKENS_PER_KB = {
    "application/pdf": 180,  # PDFs embed as document blocks; ~180 tok/KB is a
    "image/png": 12,         # conservative middle of the real range.
    "image/jpeg": 12,
    "image/jpg": 12,
    "image/gif": 12,
    "image/webp": 12,
}
_EST_TEXT_CHARS_PER_TOKEN = 3.5  # for DOCX/XLSX/CSV/TXT, estimated by size as text


def _estimate_tokens(f: DriveFile) -> int:
    """Cheap heuristic. Good enough for batch sizing and cost previews."""
    size_kb = max(1, (f.size_bytes or 0) // 1024)
    if f.google_native and f.export_mime:
        return int(size_kb * _EST_TOKENS_PER_KB.get(f.export_mime, 120))
    rate = _EST_TOKENS_PER_KB.get(f.mime_type)
    if rate is not None:
        return int(size_kb * rate)
    # Text-like default: assume ~1 token per 3.5 bytes of content.
    return int((f.size_bytes or 0) / _EST_TEXT_CHARS_PER_TOKEN)


# File-extension policy for the UI's "skip" vs "process" hints.
_CAD_EXTS = (".dwg", ".dxf", ".dwf", ".rvt", ".skp", ".stl", ".step", ".iges")
_VIDEO_AUDIO_EXTS = (
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".flac"
)
_ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz")
_SUPPORTED_EXTS = (
    ".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff",
)


def classify_extension(name: str) -> str:
    """Return 'supported' | 'cad' | 'media' | 'archive' | 'other'."""
    ext = pathlib.Path(name).suffix.lower()
    if ext in _CAD_EXTS: return "cad"
    if ext in _VIDEO_AUDIO_EXTS: return "media"
    if ext in _ARCHIVE_EXTS: return "archive"
    if ext in _SUPPORTED_EXTS: return "supported"
    return "other"


@dataclass
class ScanResult:
    folder_id: str
    folder_name: str | None
    files: list[dict[str, Any]] = field(default_factory=list)
    total_size_bytes: int = 0
    est_total_tokens: int = 0


def scan_folder(
    url_or_id: str,
    recursive: bool = True,
    creds=None,
) -> ScanResult:
    """Fast metadata scan: returns a JSON-friendly list of files with size /
    path / token-and-cost estimates. No downloads.
    """
    folder_id = parse_folder_id(url_or_id)
    service = _build_service(creds)
    folder_name = _folder_name(service, folder_id)
    listed = list_folder(folder_id, recursive=recursive, service=service)

    out = ScanResult(folder_id=folder_id, folder_name=folder_name)
    for f in listed:
        if f.skipped_reason:
            kind = "skipped"
            est = 0
        else:
            kind = classify_extension(f.name) if not f.google_native else "supported"
            est = _estimate_tokens(f)
        out.files.append({
            "id": f.id,
            "name": f.name,
            "path": f.path,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "google_native": f.google_native,
            "export_mime": f.export_mime,
            "kind": kind,
            "skipped_reason": f.skipped_reason,
            "est_tokens": est,
        })
        out.total_size_bytes += f.size_bytes
        out.est_total_tokens += est
    return out


# ---- Single-file streaming download (for one-at-a-time processing) --------

def download_one(
    file_entry: dict[str, Any],
    creds=None,
    service=None,
) -> tuple[str, bytes]:
    """Download one scanned file. Accepts an entry from ScanResult.files.

    Returns (display_name, bytes). display_name incorporates the folder path
    when present, matching download_folder_contents' naming.
    """
    service = service or _build_service(creds)
    fid = file_entry["id"]
    name = file_entry["name"]
    google_native = file_entry.get("google_native", False)
    export_mime = file_entry.get("export_mime")
    path = file_entry.get("path") or ""

    if google_native and export_mime:
        data = _export_google(service, fid, export_mime)
    else:
        data = _download_regular(service, fid)

    display = f"{path}/{name}" if path else name
    return display, data


def download_folder_contents(
    url_or_id: str,
    recursive: bool = True,
    max_file_bytes: int | None = 250 * 1024 * 1024,
    max_total_bytes: int | None = 8 * 1024 * 1024 * 1024,
    skip_unsupported: bool = True,
    progress: Callable[[DriveProgress], None] | None = None,
    creds=None,
) -> DriveDownloadResult:
    """Download every supported file in a Drive folder.

    Returns a DriveDownloadResult holding (name, bytes) tuples compatible with
    the ingest pipeline, plus a list of skipped files with reasons.

    Size caps default to 250 MB per file and 8 GB total. Pass None to disable.
    """
    folder_id = parse_folder_id(url_or_id)
    service = _build_service(creds)

    name = _folder_name(service, folder_id)
    if progress:
        progress(DriveProgress(stage="listing", filename=name or folder_id))

    listed = list_folder(folder_id, recursive=recursive, service=service)
    result = DriveDownloadResult(folder_id=folder_id, folder_name=name, listed=len(listed))

    taken: set[str] = set()
    for idx, f in enumerate(listed):
        if progress:
            progress(DriveProgress(
                stage="downloading",
                file_index=idx,
                file_count=len(listed),
                filename=f.name,
                bytes_downloaded=result.total_bytes,
            ))

        if f.skipped_reason:
            if skip_unsupported:
                result.skipped.append({
                    "name": f.name, "mime_type": f.mime_type,
                    "path": f.path, "reason": f.skipped_reason,
                })
                continue

        # Accept Google-native exports unconditionally; for regular files,
        # we could enforce the supported-MIME list, but the ingest pipeline
        # already has a fallback for unknown types, so just let them through.
        if (not f.google_native
                and not skip_unsupported
                and f.mime_type not in _SUPPORTED_REGULAR_MIMES):
            pass

        if max_file_bytes is not None and f.size_bytes and f.size_bytes > max_file_bytes:
            result.skipped.append({
                "name": f.name, "mime_type": f.mime_type, "path": f.path,
                "reason": f"file exceeds per-file cap ({f.size_bytes/1e6:.0f} MB > "
                          f"{max_file_bytes/1e6:.0f} MB)",
            })
            continue
        if max_total_bytes is not None and result.total_bytes >= max_total_bytes:
            result.skipped.append({
                "name": f.name, "mime_type": f.mime_type, "path": f.path,
                "reason": "total download cap reached — remaining files skipped",
            })
            continue

        try:
            if f.google_native and f.export_mime:
                data = _export_google(service, f.id, f.export_mime)
            else:
                data = _download_regular(service, f.id)
        except Exception as e:
            result.skipped.append({
                "name": f.name, "mime_type": f.mime_type, "path": f.path,
                "reason": f"download failed: {e}",
            })
            continue

        display = f.name if not f.path else f"{f.path}/{f.name}"
        unique = _unique_name(display, taken)
        result.files.append((unique, data))
        result.total_bytes += len(data)

    if progress:
        progress(DriveProgress(
            stage="downloading",
            file_index=len(listed), file_count=len(listed),
            bytes_downloaded=result.total_bytes, total_bytes=result.total_bytes,
        ))
    return result
