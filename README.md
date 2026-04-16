# Lobstermen Estimating App

AI-powered batch project analyzer for UMA geotechnical bids.

**Inputs:** bid package files (PDFs, Excel, images, Word, site photos) + manual project metadata
**Outputs:**
1. `01_Takeoff.xlsx` — quantity takeoff in UMA template format (pastes into master estimator)
2. `02_Project_Info.docx` — scope summary, testing/design requirements, unknowns, risks, equipment, vendors
3. `03_Vendor_RFQs.docx` — one-per-vendor RFQ drafts with project-specific takeoff tables
4. `04_Cost_Proposal.docx` — first draft cost proposal

## Running locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with your ANTHROPIC_API_KEY
streamlit run app.py
```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub
2. Go to https://share.streamlit.io → New app → pick repo, branch=main, main file=app.py
3. In the app's Secrets panel, paste:
   ```
   ANTHROPIC_API_KEY = "sk-ant-api03-..."
   ```
4. Deploy

## Architecture

```
app.py                 # Streamlit UI (landing, create-estimate, results)
src/
  ingest.py            # Parse PDF/Excel/image/docx into text + image blocks
  analyze.py           # Call Claude Sonnet 4.5 with structured prompt
  prompts/system.md    # System prompt (UMA estimating context)
  outputs/
    takeoff.py         # Output 1: xlsx
    project_info.py    # Output 2: docx
    vendor_rfqs.py     # Output 3: docx (multi-section)
    proposal.py        # Output 4: docx
```
