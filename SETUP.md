# Setup Guide — Google Drive Integration

Follow these steps once. After this, Tony (or anyone at UMA) can drop a bid
package into a shared Drive folder, paste the folder link, and the app will
stream the files server-side — no more 1 GB upload limits.

---

## Overview

The app uses a **Google Service Account** to read files from your bid-package
folders. You create the service account once in Google Cloud Console,
generate a JSON key, drop the key into the app's secrets, and share each
bid-package folder with the service account's email (just like sharing with a
teammate).

**Security:** the service account has read-only access and only to folders
you explicitly share with it. You can revoke access any time by removing the
sharing on a folder.

---

## Part A — Google Cloud setup (one-time, ~10 minutes)

### 1. Create a GCP project

1. Go to <https://console.cloud.google.com/>.
2. Click the **project dropdown** in the top bar → **New Project**.
3. Name it `uma-estimating` (or whatever you like). Click **Create**.
4. Wait for the project to be created, then make sure it's selected in the
   top-bar dropdown.

### 2. Enable the Google Drive API

1. In the left nav, go to **APIs & Services → Library**.
2. Search for **Google Drive API**.
3. Click it, then click **Enable**.

### 3. Create a Service Account

1. Go to **APIs & Services → Credentials**.
2. Click **Create credentials → Service account**.
3. Service account name: `uma-estimating-reader`.
4. Click **Create and continue**. Skip the "Grant access" step (leave blank)
   and click **Done**. The service account does not need any IAM roles —
   Drive uses resource-level sharing, not IAM.
5. Find your new service account in the Credentials list. Note its email,
   which looks like:
   `uma-estimating-reader@uma-estimating.iam.gserviceaccount.com`

### 4. Generate a JSON key

1. Click the service account's email to open its detail page.
2. Go to the **Keys** tab.
3. Click **Add key → Create new key**.
4. Select **JSON** and click **Create**. A `.json` file downloads to your
   machine. **Keep this file safe — it's a credential.**

---

## Part B — Configure the app

Pick the subsection that matches how you're deploying.

### B1. Streamlit Cloud (the `main` branch)

1. In your Streamlit Cloud app's **Settings → Secrets**, add a
   `google_service_account` section whose value is the **entire contents**
   of the JSON file:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-api03-..."

   [google_service_account]
   type = "service_account"
   project_id = "uma-estimating"
   private_key_id = "..."
   private_key = """-----BEGIN PRIVATE KEY-----
   ...
   -----END PRIVATE KEY-----
   """
   client_email = "uma-estimating-reader@uma-estimating.iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   universe_domain = "googleapis.com"
   ```

   Use triple-quoted strings for `private_key` so the newlines are
   preserved.

2. Save and redeploy the app. Streamlit will show a "Drive connected"
   indicator on the Create-Estimate page when it picks up the secret.

### B2. Tasklet Instant App (the `tasklet-instant-app` branch)

Tasklet provides environment variables to the Python sandbox. You have two
ways to supply the key:

**Option 1 (recommended):** add an env var named `GOOGLE_SERVICE_ACCOUNT_JSON`
whose value is the **entire JSON file as a single line**. Use a JSON
minifier (or `jq -c . key.json | pbcopy` on macOS) to collapse the file to
one line, then paste it as the value.

**Option 2:** upload the JSON key to the Tasklet sandbox and set
`GOOGLE_APPLICATION_CREDENTIALS` to its path.

The backend picks up whichever is set.

### B3. Local development (optional)

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/key.json
python -m backend.server --port 8787 --output-dir /tmp/uma-out
# open http://localhost:8787
```

---

## Part C — Share each bid-package folder

For every project you want to analyze:

1. Put the bid package files into a folder in Google Drive (subfolders are
   OK — the app recurses).
2. Right-click the folder → **Share**.
3. Paste the service account email
   (`uma-estimating-reader@…iam.gserviceaccount.com`) and set the role to
   **Viewer**.
4. Click **Send** (uncheck "Notify people" — it's not a real mailbox).

That's it. From now on, any folder you share with that email is readable by
the app. You can share the whole **Lobstermen HQ** folder once and every
subfolder inherits access.

---

## How to use it

1. In the app, choose the **Google Drive folder** tab.
2. Paste the folder URL (e.g.,
   `https://drive.google.com/drive/folders/1DojM9abz4nEXvWzGLZkCZQ4qEmLUZ0hn`)
   and hit **Scan folder**.
3. Review the file list. Supported files (PDF, DOCX, XLSX, images) are
   selected by default. CAD files are tagged and unselected (Claude can't
   read `.dwg`). Media files and archives are also unselected.
4. Adjust your selection if needed, then hit **Analyze & generate**.
5. The app streams each file one at a time, sends batched content to Claude,
   and produces the four deliverables. For a 50-file package expect 5-10
   minutes total.

---

## Part D — Smart Vision for plan sheets (optional but recommended)

The app has a vision preprocessor for construction plan PDFs. When you
upload a drawing it:

1. Extracts dimension lines, symbols, and scale directly from the PDF's
   vector data (free, deterministic — no Claude call).
2. Rasterizes each page at 150 DPI and splits it into 5 overlapping regions.
3. Sends each region to Claude with a sheet-type-specific prompt in parallel.
4. Merges results and passes the structured data to the main analysis as
   ground-truth context.

Nothing to configure per-project. The rasterization step uses poppler when
available and falls back to `pdfplumber.page.to_image()` (which ships with
the `pdfplumber` dep) otherwise, so this still works without system
packages — just with slightly lower rendering quality.

### Install poppler (faster, higher quality)

macOS: `brew install poppler`
Ubuntu / Debian: `sudo apt-get install poppler-utils`

### Streamlit Cloud

The repo has a `packages.txt` at the root listing `poppler-utils`; Streamlit
Cloud auto-installs it on each deploy. No manual step needed.

### Tasklet

If the Tasklet sandbox doesn't already have `pdftoppm` on the PATH, the
fallback path will be used automatically. To force the high-quality path,
add `poppler-utils` to the Tasklet sandbox config.

---

## Troubleshooting

**"No Google Drive credentials available"** — the service account JSON isn't
configured. Re-check Part B for your deployment.

**"Could not parse a Drive folder ID"** — paste either a bare folder ID
(the long alphanumeric string) or a URL that contains `/folders/<ID>`.

**"File not found" or 404 on scan** — the folder isn't shared with the
service account. Follow Part C.

**"The caller does not have permission"** — same as above; the folder needs
to be shared with the service account email as Viewer.

**Individual file download fails with `cannotDownloadFile`** — Drive blocks
downloads of a handful of Google-native types (Forms, Jamboards). The app
skips these automatically and notes them in the `skipped[]` list.

**Estimated cost too high** — the preview shows cost at ~$3/M input tokens.
Reduce selection to the files that actually matter, or split a huge plan set
across multiple runs.
