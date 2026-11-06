# SME GST and Invoice Compliance Copilot

Upload an invoice (PDF or scan) → OCR → structured extraction → GST rule checks → law-grounded RAG → **ITC verdict + action list + supplier follow-up message**.

## Architecture
```
Upload → OCR (pdfplumber / Tesseract) → Extractor Agent (LLM → Pydantic Invoice)
       → Validator Agent (deterministic: GSTIN checksum, IGST/CGST-SGST, totals, Rule 46, HSN, rate slabs, Sec 16(4) time-bar, IRN)
       → Legal Researcher Agent (RAG over CGST Act / circulars, Sec 17(5) blocked-credit check)
       → Advisor Agent (verdict, actions, supplier message)      [LangGraph StateGraph]
FastAPI: /analyze  /analyze-batch  /ask  /reindex  /health   →  Docker → AWS
```
Design choice: **numbers and rules are checked in code, not by the LLM.** The LLM is used only for extraction, legal explanation and advice. The advisor can return "ITC_ELIGIBLE" only when there are no errors (hard guard).

## Quick start (pyproject)
```bash
cp .env.example .env            # set OPENAI_API_KEY
make install samples test index eval
make api   # or: make ui
```
Data checklist: `data/README.md`. Regenerate the notebook with `python build_notebook.py`.

## Run locally
```bash
pip install -r requirements.txt          # + apt: tesseract-ocr poppler-utils
export OPENAI_API_KEY=sk-...
python test_validators.py                # offline tests (no key needed)
# Put the CGST Act, Rules and circulars (PDFs from cbic-gst.gov.in) in data/gst_docs/
uvicorn app:app --reload                 # http://localhost:8000/docs
curl -F file=@samples/invoice1.pdf localhost:8000/analyze
curl -X POST localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"Is ITC allowed on employee food expenses?"}'
```

## Samples + Streamlit UI
```bash
pip install -r requirements-dev.txt
python generate_samples.py               # creates 9 PDFs + 1 scanned PNG + expected.json in samples/
streamlit run streamlit_app.py           # http://localhost:8501
```
| Sample | Expected |
|---|---|
| 01_clean_intrastate | ITC_ELIGIBLE |
| 02_bad_gstin_checksum | GSTIN checksum error |
| 03_igst_on_intrastate | TAX_TYPE_MISMATCH |
| 04_cgst_sgst_on_interstate | TAX_TYPE_MISMATCH |
| 05_total_mismatch | TOTAL_MISMATCH |
| 06_long_invoice_number | INV_NO_FORMAT (Rule 46) |
| 07_itc_time_barred_2024 | ITC_TIME_BAR (Sec 16(4)) |
| 08_hotel_food_sec17_5 | ITC_BLOCKED via RAG (the knowledge base must cover Sec 17(5)) |
| 09_missing_irn_hsn | HSN_MISSING + IRN_ABSENT |
| 10_scanned_clean.png | OCR path (totals and IRN may come out noisy — a realistic test for the extractor) |

The UI has three tabs: single invoice (upload or pick a sample), batch (with CSV download) and Ask GST law. Enter a deployed API URL in the sidebar to point the same UI at the AWS service.

## AWS deployment (simplest: ECR + App Runner)
```bash
aws ecr create-repository --repository-name gst-copilot --region ap-south-1
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.ap-south-1.amazonaws.com
docker build -t gst-copilot . && docker tag gst-copilot:latest <ACCOUNT>.dkr.ecr.ap-south-1.amazonaws.com/gst-copilot:latest
docker push <ACCOUNT>.dkr.ecr.ap-south-1.amazonaws.com/gst-copilot:latest
```
Then in the console: **App Runner → Create service** → source: the ECR image, port `8000`, env var `OPENAI_API_KEY` (preferably from Secrets Manager), health check path `/health`, 1 vCPU / 2 GB.
Alternative: on an EC2 instance (t3.small), run `docker run -p 80:8000 -e OPENAI_API_KEY=... <image>`.
Tip: store `data/faiss_index` on S3 and download it at startup so the index is not re-embedded on every deploy.

## Important notes
- Rate slabs: the new regime applies from 22-Sep-2025 (5/18/40 plus special 0/0.25/3). For invoices dated before that, the legacy 12/28% slabs are treated as valid. **Verify the exact HSN-wise rate against the notification** — the rate check only raises a warning.
- The Sec 16(4) deadline, Rule 46 and e-invoice thresholds change from time to time — update the rules from CBIC notifications before using this in production.
- This tool assists with compliance; the final filing decision rests with a CA or tax professional.

## Demo script (capstone presentation)
1. Clean invoice → ITC_ELIGIBLE. 2. Invoice with a wrong GSTIN checksum → error flag. 3. Maharashtra buyer charged CGST+SGST → TAX_TYPE_MISMATCH. 4. "Hotel stay" invoice → Sec 17(5) via RAG. 5. Run `/analyze-batch` on 10 invoices → summary counts.
