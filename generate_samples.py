"""Sample GST invoices (PDFs plus one scanned PNG) — each covers a different compliance scenario.
Run: python generate_samples.py  ->  samples/*.pdf  + samples/expected.json
"""
import json
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

OUT = Path("samples"); OUT.mkdir(exist_ok=True)
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(body14: str) -> str:
    t = 0
    for i, ch in enumerate(body14):
        p = _B36.index(ch) * (1 if i % 2 == 0 else 2); t += p // 36 + p % 36
    return body14 + _B36[(36 - t % 36) % 36]


SUP_TS = gstin("36AABCU9603R1Z")   # Telangana supplier
BUY_TS = gstin("36AAACR5055K1Z")   # Telangana buyer
BUY_MH = gstin("27AAPFU0939F1Z")   # Maharashtra buyer
STATE = {"36": "Telangana (36)", "27": "Maharashtra (27)"}


def make(fname, *, inv_no="INV/26-27/0142", date="10-08-2026", sup=SUP_TS, buy=BUY_TS, sup_name="Nimbus Software Pvt Ltd",
         buy_name="Rao Traders LLP", items=None, rate=18, cgst=None, sgst=None, igst=None, total=None, irn=True):
    items = items or [("Software development services", "998314", 1, 50000.0)]
    taxable = sum(q * p for _, _, q, p in items)
    tax = taxable * rate / 100
    intra = sup[:2] == buy[:2]
    cgst = (tax / 2 if intra else 0) if cgst is None else cgst
    sgst = (tax / 2 if intra else 0) if sgst is None else sgst
    igst = (0 if intra else tax) if igst is None else igst
    total = round(taxable + cgst + sgst + igst, 2) if total is None else total
    ss = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT / fname), pagesize=A4, topMargin=36, bottomMargin=36)
    el = [Paragraph("TAX INVOICE", ss["Title"]),
          Paragraph(f"<b>{sup_name}</b><br/>GSTIN: {sup}", ss["Normal"]), Spacer(1, 8),
          Paragraph(f"Invoice No: {inv_no}<br/>Invoice Date: {date}<br/>Place of Supply: {STATE[buy[:2]]}", ss["Normal"]), Spacer(1, 8),
          Paragraph(f"<b>Bill To:</b> {buy_name}<br/>Buyer GSTIN: {buy}", ss["Normal"]), Spacer(1, 12)]
    rows = [["#", "Description", "HSN/SAC", "Qty", "Rate", "Taxable Value", "GST %"]]
    for n, (d, h, q, p) in enumerate(items, 1):
        rows.append([n, d, h, q, f"{p:,.2f}", f"{q*p:,.2f}", f"{rate}%"])
    t = Table(rows, colWidths=[20, 190, 60, 30, 65, 80, 40])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    el += [t, Spacer(1, 12)]
    tot = [["Taxable Value", f"{taxable:,.2f}"], ["CGST", f"{cgst:,.2f}"], ["SGST", f"{sgst:,.2f}"], ["IGST", f"{igst:,.2f}"], ["Total Invoice Value", f"{total:,.2f}"]]
    tt = Table(tot, colWidths=[150, 100], hAlign="RIGHT"); tt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    el.append(tt)
    if irn:
        el += [Spacer(1, 10), Paragraph("IRN: " + "a3f9" * 16, ss["Normal"])]
    doc.build(el)


SCENARIOS = {
    "01_clean_intrastate.pdf": ({}, "ITC_ELIGIBLE", "No issues"),
    "02_bad_gstin_checksum.pdf": (dict(sup=SUP_TS[:-1] + ("A" if SUP_TS[-1] != "A" else "B")), "ITC_AT_RISK", "SUPPLIER_GSTIN_CHECKSUM"),
    "03_igst_on_intrastate.pdf": (dict(cgst=0, sgst=0, igst=9000), "ITC_AT_RISK", "TAX_TYPE_MISMATCH"),
    "04_cgst_sgst_on_interstate.pdf": (dict(buy=BUY_MH, buy_name="Pune Retail Pvt Ltd", cgst=4500, sgst=4500, igst=0), "ITC_AT_RISK", "TAX_TYPE_MISMATCH"),
    "05_total_mismatch.pdf": (dict(total=61500.0), "ITC_AT_RISK", "TOTAL_MISMATCH"),
    "06_long_invoice_number.pdf": (dict(inv_no="NIMBUS-SOFTWARE-2026-27-INV-000142"), "ITC_AT_RISK", "INV_NO_FORMAT"),
    "07_itc_time_barred_2024.pdf": (dict(date="01-06-2024"), "ITC_AT_RISK", "ITC_TIME_BAR (Sec 16(4))"),
    "08_hotel_food_sec17_5.pdf": (dict(sup_name="Hotel Deccan Grand", items=[("Banquet hall & outdoor catering - staff party", "996334", 1, 40000.0)], rate=18),
                                  "ITC_BLOCKED", "Sec 17(5) via RAG (food/catering)"),
    "09_missing_irn_hsn.pdf": (dict(irn=False, items=[("Consulting services", "", 1, 25000.0)]), "ITC_AT_RISK", "HSN_MISSING, IRN_ABSENT"),
}

if __name__ == "__main__":
    exp = {}
    for fname, (kw, verdict, why) in SCENARIOS.items():
        make(fname, **kw); exp[fname] = {"expected_verdict": verdict, "expected_flags": why}
    # Scanned-style PNG (OCR test): the clean invoice rendered as an image with slight noise and rotation
    try:
        from pdf2image import convert_from_path
        from PIL import ImageFilter
        im = convert_from_path(str(OUT / "01_clean_intrastate.pdf"), dpi=200)[0].convert("L").rotate(0.8, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
        im.save(OUT / "10_scanned_clean.png"); exp["10_scanned_clean.png"] = {"expected_verdict": "ITC_ELIGIBLE", "expected_flags": "OCR path test"}
    except Exception as e:
        print("PNG skip:", e)
    (OUT / "expected.json").write_text(json.dumps(exp, indent=2, ensure_ascii=False))
    print(f"{len(exp)} samples -> {OUT}/")
