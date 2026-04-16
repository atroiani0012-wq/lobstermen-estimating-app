# Lobstermen Estimating App

AI-powered batch project analyzer for UMA geotechnical bids.

**Inputs:** bid package files (PDFs, Excel, images, Word, site photos) + manual project metadata. Optionally pull files from Google Drive via service-account authentication.
**Outputs:**
1. `01_Takeoff.xlsx` — quantity takeoff in UMA template format (pastes into master estimator)
2. `02_Project_Info.docx` — scope summary, testing/design requirements, unknowns, risks, equipment, vendors
3. `03_Vendor_RFQs.docx` — one-per-vendor RFQ drafts with project-specific takeoff tables
4. `04_Cost_Proposal.docx` — first draft cost proposal
5. `05_Bidder_List.xlsx` — prospective bidders discovered via web research (when available)

## Running locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with your ANTHROPIC_API_KEY and (optionally) GDRIVE_SERVICE_ACCOUNT
streamlit run app.py
```

### Google Drive integration (optional)

To pull bid packages from a shared Google Drive folder:

1. **Create a service account:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project or select an existing one
   - Enable the Google Drive API
   - Create a service account and download the private key as JSON

2. **Share the Drive folder:**
   - Share the project folder (with the bid documents) with the service account's email address (e.g., `xxx@xxx.iam.gserviceaccount.com`)
   - Grant at least Viewer access

3. **Add the secret:**
   - In `.streamlit/secrets.toml` (or Streamlit Cloud's Secrets panel), add:
     ```toml
     GDRIVE_SERVICE_ACCOUNT = """
     {
       "type": "service_account",
       "project_id": "xxx",
       ...
     }
     """
     ```
     Or (if you prefer a TOML table instead of a JSON string):
     ```toml
     [GDRIVE_SERVICE_ACCOUNT]
     type = "service_account"
     project_id = "xxx"
     ...
     ```

4. **Use in the app:**
   - On the Create Estimate page, paste the Drive folder URL (e.g., `https://drive.google.com/drive/folders/1abc...XYZ`)
   - The app will recursively pull all files, skipping certain folders (e.g., `Estimates`, `Proposals`, `Correspondence`)

### Web research feature

The app uses Anthropic's server-side `web_search` tool to research the project:
- **Anthropic API key must have server-side tool access** (enabled by default for paid accounts)
- Claude can execute up to 15 searches per analysis
- Searches target project owner, bidder lists, public lettings, specs, and vendor availability
- Results feed into a 5th output file: `05_Bidder_List.xlsx`

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub
2. Go to https://share.streamlit.io → New app → pick repo, branch=main, main file=app.py
3. In the app's Secrets panel, paste:
   ```
   ANTHROPIC_API_KEY = "sk-ant-api03-..."
   ```
4. Deploy

## Runtime constraints

- **Max analysis runtime:** 30 minutes. If the pre-flight estimate exceeds ~24 min (80% margin), the app will warn and ask for confirmation before proceeding.
- **Max file size:** 5 GB per file
- **Web searches:** Up to 15 per analysis run, executed in parallel with file analysis

## Architecture

```
app.py                 # Streamlit UI (landing, create-estimate, results)
src/
  ingest.py            # Parse PDF/Excel/image/docx into text + image blocks
  analyze.py           # Call Claude Sonnet 4.5 with structured prompt + web_search tool
  drive_pull.py        # Pull files from Google Drive (via service account)
  prompts/system.md    # System prompt (UMA estimating context + web research directives)
  outputs/
    takeoff.py         # Output 1: xlsx
    project_info.py    # Output 2: docx
    vendor_rfqs.py     # Output 3: docx (multi-section)
    proposal.py        # Output 4: docx
    bidder_list.py     # Output 5: xlsx (from web_research.bidder_list)
```
