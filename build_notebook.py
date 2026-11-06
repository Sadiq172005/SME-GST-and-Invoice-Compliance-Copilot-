"""pipeline.py + extra sections -> gst_compliance_copilot.ipynb  (run: python build_notebook.py)"""
import re, nbformat as nbf
M, C = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
src = open("pipeline.py").read()
sections = dict(zip(*[iter(re.split(r"^# %% (.+)$", src, flags=re.M)[1:])] * 2))

nb = nbf.v4.new_notebook(); c = nb.cells
c += [M("""# SME GST and Invoice Compliance Copilot
**Problem:** Catching errors in purchase invoices (wrong GSTIN, wrong tax type, total mismatch, blocked ITC) by hand is slow and risky — it leads to ITC loss and notices.
**Solution:** OCR → LLM extraction → deterministic GST rule engine → RAG over GST law → 4-agent LangGraph → ITC verdict + actions.

**Contents:** 0 Setup · 1 Architecture · 2 Data · 3 Schemas · 4 OCR · 5 Extraction · 6 Rule engine · 7 RAG · 8 Agents · 9 Orchestration · 10 Demo · 11 Evaluation · 12 API + UI · 13 Deployment · 14 Limitations & next steps"""),
      M("## 0. Setup\nSystem packages (install outside the notebook): `sudo apt install tesseract-ocr poppler-utils` (Mac: `brew install tesseract poppler`).\nPython: `pip install -e \".[all]\"` (from pyproject.toml) · set `OPENAI_API_KEY` in `.env` (copy `.env.example`)."),
      C("import shutil, os\nfrom dotenv import load_dotenv; load_dotenv()\nfor b in ['tesseract', 'pdftoppm']:\n    print(b, '✅' if shutil.which(b) else '❌ not installed')\nprint('OPENAI_API_KEY', '✅' if os.getenv('OPENAI_API_KEY') else '❌ set it in .env')"),
      M("""## 1. Architecture
```
Invoice (PDF/scan) → OCR → Extractor Agent → Validator Agent (code rules) → Legal Researcher Agent (RAG) → Advisor Agent → verdict/actions/supplier message
```
**Design decisions:** (1) tax math, GSTIN and rule checks run in **code**, so the LLM cannot hallucinate them; (2) the LLM is used only for extraction, legal explanation and advice; (3) a hard guard stops the advisor from returning "ELIGIBLE" when errors exist; (4) RAG answers come with sources."""),
      M("## 2. Data\nPlace the CGST Act, CGST Rules, IGST Act, latest rate notifications, ITC circulars and e-invoice notifications in `data/gst_docs/` (full checklist: `data/README.md`). Test invoices: `python generate_samples.py`."),
      C("from pathlib import Path\ndocs = list(Path('data/gst_docs').glob('**/*'))\nprint(len(docs), 'docs:', [d.name for d in docs][:10])\nprint(len(list(Path('samples').glob('*.pdf'))), 'sample PDFs')")]
for title in ["Setup & Config", "Schemas", "OCR", "Extraction (LLM -> structured Invoice)", "Deterministic GST validators (rule-based hard checks, no LLM)",
              "RAG — GST law knowledge base (CGST Act, rules, circulars, notifications)", "Multi-Agent System (LangGraph): Extractor -> Rule Validator -> Legal Researcher -> Advisor", "Orchestration — end-to-end"]:
    code = sections[title].strip().replace('if __name__ == "__main__":', "if False:  # CLI entrypoint — skipped in the notebook")
    hdr = {"Setup & Config": "### Config & LLM factory", "Schemas": "## 3. Schemas (Pydantic)", "OCR": "## 4. OCR\nDigital PDF → text layer; scanned → pdf2image + Tesseract.",
           "Extraction (LLM -> structured Invoice)": "## 5. Structured extraction", "Deterministic GST validators (rule-based hard checks, no LLM)": "## 6. Rule engine (deterministic)",
           "RAG — GST law knowledge base (CGST Act, rules, circulars, notifications)": "## 7. RAG over GST law", "Multi-Agent System (LangGraph): Extractor -> Rule Validator -> Legal Researcher -> Advisor": "## 8. Multi-agent system (LangGraph)",
           "Orchestration — end-to-end": "## 9. Orchestration"}[title]
    c += [M(hdr), C(code)]
    if title.startswith("Deterministic"):
        c += [M("**Offline demo (no API key needed):**"), C("""inv = Invoice(invoice_no='INV/001', invoice_date='2026-08-10', supplier_gstin='36AABCU9603R1ZX', buyer_gstin='27AAPFU0939F1ZV',
  place_of_supply='27', taxable_value=10000, cgst=900, sgst=900, total_amount=12500,
  line_items=[LineItem(description='Consulting', hsn_sac='998311', taxable_value=10000, gst_rate=18)])
for i in validate_invoice(inv): print(i.severity.upper().ljust(8), i.code.ljust(24), i.message)""")]
    if title.startswith("RAG"):
        c += [M("Build the index the first time (rebuild whenever the documents change):"), C("# build_index()   # uncomment to run — uses OpenAI embeddings (small one-time cost)\n# rag_answer('Is ITC allowed on outdoor catering?')")]
c += [M("## 10. End-to-end demo"),
      C("import json\nres = analyze_invoice('samples/03_igst_on_intrastate.pdf')\nprint(json.dumps(res['report'], indent=2, ensure_ascii=False))\nfor i in res['issues']: print(i['severity'], i['code'], '-', i['message'])"),
      M("## 11. Evaluation\nVerdicts are compared against `samples/expected.json` (`python evaluate.py`). Unit tests for the rule engine: `python test_validators.py`."),
      C("import json\nexp = json.load(open('samples/expected.json')); rows = []\nfor f, e in exp.items():\n    r = analyze_invoice(f'samples/{f}'); got = r['report']['verdict']\n    rows.append((f, e['expected_verdict'], got, 'PASS' if got == e['expected_verdict'] else 'FAIL'))\nimport pandas as pd; pd.DataFrame(rows, columns=['file', 'expected', 'got', 'result'])"),
      M("## 12. API + UI\n`uvicorn app:app --reload` → `/docs` · `streamlit run streamlit_app.py`. Endpoints: `/analyze`, `/analyze-batch`, `/ask`, `/reindex`, `/health`."),
      M("## 13. Deployment (AWS)\nDocker → ECR → App Runner (port 8000, `OPENAI_API_KEY` from Secrets Manager, health check `/health`). Store the FAISS index on S3. Full commands: `README.md`."),
      M("""## 14. Limitations & next steps
- The rate check is slab-level only; add `hsn_master.csv` for exact HSN-wise rates.
- GSTR-2B reconciliation (invoice vs portal data) is not implemented yet — next feature.
- E-invoice IRN signature/QR is not verified (presence check only).
- OCR accuracy drops on handwritten or low-quality scans; a vision-LLM fallback could be added.
- Rules (rates, deadlines, thresholds) change over time — update them periodically from CBIC notifications.
- This is a compliance *assistant*, not a substitute for a CA or tax professional. Handle PII and consent carefully when using real invoices.""")]
nbf.write(nb, "gst_compliance_copilot.ipynb"); print("cells:", len(c))
