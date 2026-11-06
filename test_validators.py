"""Offline tests — run without an LLM or API key: python test_validators.py"""
import datetime as dt
from pipeline import gstin_checksum_ok, validate_invoice, Invoice, LineItem

def codes(inv, today=dt.date(2026, 9, 29)):
    return {i.code for i in validate_invoice(inv, today)}

def make_gstin(body14):
    from pipeline import _B36
    t = 0
    for i, ch in enumerate(body14):
        p = _B36.index(ch) * (1 if i % 2 == 0 else 2); t += p // 36 + p % 36
    return body14 + _B36[(36 - t % 36) % 36]

SUP = make_gstin("36AABCU9603R1Z")   # Telangana
BUY_TS = make_gstin("36AAACR5055K1Z")
BUY_MH = make_gstin("27AAPFU0939F1Z")

def good(**kw):
    base = dict(invoice_no="INV/26-27/001", invoice_date="2026-08-10", supplier_gstin=SUP, buyer_gstin=BUY_TS,
                place_of_supply="36", taxable_value=10000, cgst=900, sgst=900, igst=0, total_amount=11800, irn="x"*64,
                line_items=[LineItem(description="Software services", hsn_sac="998314", taxable_value=10000, gst_rate=18)])
    base.update(kw); return Invoice(**base)

assert gstin_checksum_ok(SUP) and gstin_checksum_ok(BUY_MH)
assert not gstin_checksum_ok(SUP[:-1] + ("A" if SUP[-1] != "A" else "B"))
assert codes(good()) == set(), codes(good())
assert "TAX_TYPE_MISMATCH" in codes(good(igst=1800, cgst=0, sgst=0, total_amount=11800))       # IGST on an intra-state supply
assert "TAX_TYPE_MISMATCH" in codes(good(buyer_gstin=BUY_MH, place_of_supply="27"))            # CGST/SGST on an inter-state supply
assert "TOTAL_MISMATCH" in codes(good(total_amount=12500))
assert "INV_NO_FORMAT" in codes(good(invoice_no="THIS-IS-A-VERY-LONG-INVOICE-NO"))
assert "SUPPLIER_GSTIN_CHECKSUM" in codes(good(supplier_gstin="36AABCU9603R1ZX"))
assert "ITC_TIME_BAR" in codes(good(invoice_date="2024-06-01"))
assert "RATE_SLAB" in codes(good(line_items=[LineItem(hsn_sac="998314", taxable_value=10000, gst_rate=12)]))   # 12% post-Sep-2025
assert "RATE_SLAB" not in codes(good(invoice_date="2025-06-01", line_items=[LineItem(hsn_sac="998314", taxable_value=10000, gst_rate=12)]))
print("All validator tests passed ✅")
