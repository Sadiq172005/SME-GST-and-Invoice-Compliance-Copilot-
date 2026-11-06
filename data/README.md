# data/ — what you need

## 1. `data/gst_docs/` (RAG knowledge base) — REQUIRED
Download only from **official** sources (cbic-gst.gov.in, gst.gov.in, indiacode.nic.in). Both PDFs and .txt/.md files work.
Use PDFs with a text layer (not scans), otherwise retrieval quality will suffer.

| Document | Why it is needed |
|---|---|
| CGST Act 2017 (updated/consolidated) | Sec 16, 17(5), 34, 31 — ITC eligibility, blocked credits, credit notes |
| CGST Rules 2017 (consolidated) | Rule 36, 37, 46 (invoice contents), 47 (time limit), 48 (e-invoice) |
| IGST Act 2017 | Place of supply (Sec 10-13) — IGST vs CGST/SGST logic |
| Rate notifications (goods + services), latest, effective 22-Sep-2025 | Rate slab / HSN-wise rate questions |
| Exemption notifications | 0% / exempt supply queries |
| ITC-related CBIC circulars (GSTR-2B reconciliation, Sec 16(2)(aa), time limits) | Legal notes for the advisor |
| E-invoice notifications / FAQs | IRN threshold, QR code rules |
| CBIC FAQs on ITC / invoicing | Plain-language grounding |

## 2. Optional (to improve accuracy)
- `data/hsn_master.csv` — HSN/SAC code + description + rate (from CBIC/GSTN). It would let the validator check exact HSN-wise rates (today it only checks rate slabs).
- `data/state_codes.csv` — not needed; the state codes are currently hardcoded.

## 3. Generated (do not commit)
- `data/faiss_index/` — built by `make index`; rebuild it (or call `/reindex`) whenever the documents change.

## 4. Test data
- `samples/` — created by `python generate_samples.py` (synthetic invoices; no real GSTIN or company data).
- If you use real client invoices, handle **masking and consent** carefully (PII: GSTIN, names, amounts).
