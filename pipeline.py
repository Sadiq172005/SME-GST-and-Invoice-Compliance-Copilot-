# %% Setup & Config
"""GST / Invoice Compliance Copilot — OCR -> Extraction -> Rules + RAG -> Multi-Agent (LangGraph)."""
import os, re, json, datetime as dt
from pathlib import Path
from typing import List, Optional, TypedDict, Literal

from pydantic import BaseModel, Field

try:                                   # load OPENAI_API_KEY etc. from .env (optional)
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
DOCS_DIR = Path(os.getenv("GST_DOCS_DIR", "data/gst_docs"))
INDEX_DIR = Path(os.getenv("INDEX_DIR", "data/faiss_index"))
# The OPENAI_API_KEY environment variable is required (LLM + embeddings)


def get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=LLM_MODEL, temperature=0)


# %% Schemas
class LineItem(BaseModel):
    description: str = ""
    hsn_sac: Optional[str] = None
    quantity: Optional[float] = None
    taxable_value: Optional[float] = None
    gst_rate: Optional[float] = Field(None, description="Total GST rate in percent, e.g. 18")


class Invoice(BaseModel):
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    place_of_supply: Optional[str] = Field(None, description="State name or 2-digit state code")
    irn: Optional[str] = None
    line_items: List[LineItem] = []
    taxable_value: Optional[float] = None
    cgst: Optional[float] = 0.0
    sgst: Optional[float] = 0.0
    igst: Optional[float] = 0.0
    cess: Optional[float] = 0.0
    total_amount: Optional[float] = None


class Issue(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    fix: Optional[str] = None


# %% OCR
def ocr_document(path: str) -> str:
    """Handles PDFs (text-layer or scanned) and images."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        except Exception:
            pass
        if len(text.strip()) > 40:          # digital PDF — no OCR needed
            return text
        from pdf2image import convert_from_path
        import pytesseract
        return "\n".join(pytesseract.image_to_string(im, config="--psm 6")
                         for im in convert_from_path(path, dpi=250))
    import pytesseract
    from PIL import Image, ImageOps
    im = ImageOps.grayscale(Image.open(path))
    return pytesseract.image_to_string(im, config="--psm 6")


# %% Extraction (LLM -> structured Invoice)
EXTRACT_PROMPT = """You are an Indian GST invoice parser. Extract fields from the OCR text.
Rules: dates as YYYY-MM-DD; amounts as plain numbers (no commas/currency); GSTINs uppercase, 15 chars;
if a field is absent use null. Do NOT guess or fix values — copy exactly what is printed, even if it looks wrong.
OCR TEXT:
{text}"""


def extract_invoice(text: str) -> Invoice:
    llm = get_llm().with_structured_output(Invoice)
    return llm.invoke(EXTRACT_PROMPT.format(text=text[:12000]))


# %% Deterministic GST validators (rule-based hard checks, no LLM)
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}
NEW_REGIME_DATE = dt.date(2025, 9, 22)   # GST rate rationalisation (5/18/40) — legacy 12/28 slabs no longer apply after this date
RATES_NEW = {0, 0.25, 1.5, 3, 5, 18, 40}
RATES_LEGACY = RATES_NEW | {12, 28}


def gstin_checksum_ok(g: str) -> bool:
    total = 0
    for i, ch in enumerate(g[:14]):
        prod = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return _B36[(36 - total % 36) % 36] == g[14]


def _state_code(pos: Optional[str]) -> Optional[str]:
    if not pos:
        return None
    m = re.match(r"\s*(\d{2})", pos)
    if m:
        return m.group(1)
    for code, name in STATE_CODES.items():
        if name.lower() in pos.lower() or pos.lower() in name.lower():
            return code
    return None


def _d(s: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _gstin_issues(label: str, g: Optional[str], required: bool) -> List[Issue]:
    if not g:
        return [Issue(code=f"{label}_GSTIN_MISSING", severity="error" if required else "info",
                      message=f"{label} GSTIN missing.",
                      fix="Supplier GSTIN is mandatory; for B2B invoices the buyer GSTIN is also required to claim ITC." if required else None)]
    g = g.strip().upper()
    if not GSTIN_RE.match(g):
        return [Issue(code=f"{label}_GSTIN_FORMAT", severity="error", message=f"{label} GSTIN '{g}' has an invalid format.",
                      fix="15-char format: 2-digit state + PAN(10) + entity + Z + checksum.")]
    if g[:2] not in STATE_CODES:
        return [Issue(code=f"{label}_GSTIN_STATE", severity="error", message=f"{label} GSTIN has an invalid state code ({g[:2]}).")]
    if not gstin_checksum_ok(g):
        return [Issue(code=f"{label}_GSTIN_CHECKSUM", severity="error",
                      message=f"{label} GSTIN '{g}' failed the checksum — possible typo or fake GSTIN.",
                      fix="Verify on the GST portal using 'Search Taxpayer'.")]
    return []


def validate_invoice(inv: Invoice, today: Optional[dt.date] = None) -> List[Issue]:
    today = today or dt.date.today()
    out: List[Issue] = []
    b2b = bool(inv.buyer_gstin)

    out += _gstin_issues("SUPPLIER", inv.supplier_gstin, True)
    if inv.buyer_gstin:
        out += _gstin_issues("BUYER", inv.buyer_gstin, False)

    # Rule 46: invoice no. <=16 chars, alnum + / -
    if not inv.invoice_no:
        out.append(Issue(code="INV_NO_MISSING", severity="error", message="Invoice number missing."))
    elif len(inv.invoice_no) > 16 or not re.fullmatch(r"[A-Za-z0-9/\-]+", inv.invoice_no):
        out.append(Issue(code="INV_NO_FORMAT", severity="error",
                         message=f"Invoice no. '{inv.invoice_no}' violates Rule 46 (max 16 characters; only alphanumerics, '/' and '-' allowed).",
                         fix="Reformat the invoice number series."))

    date = _d(inv.invoice_date)
    if not date:
        out.append(Issue(code="DATE_INVALID", severity="error", message="Invoice date missing/invalid."))
    elif date > today:
        out.append(Issue(code="DATE_FUTURE", severity="error", message="Invoice date is in the future."))
    else:
        # Sec 16(4): ITC deadline = 30 Nov following FY end
        fy_end_year = date.year + 1 if date.month >= 4 else date.year
        deadline = dt.date(fy_end_year, 11, 30)
        if today > deadline:
            out.append(Issue(code="ITC_TIME_BAR", severity="warning",
                             message=f"The Sec 16(4) ITC deadline ({deadline}) has passed — claiming ITC is risky.",
                             fix="Check whether a credit note, amendment or special extension applies."))

    # Place of supply -> IGST vs CGST+SGST
    sup_code = (inv.supplier_gstin or "")[:2]
    pos_code = _state_code(inv.place_of_supply) or ((inv.buyer_gstin or "")[:2] or None)
    cgst, sgst, igst = (inv.cgst or 0), (inv.sgst or 0), (inv.igst or 0)
    if sup_code in STATE_CODES and pos_code:
        intra = sup_code == pos_code
        if intra and igst > 0:
            out.append(Issue(code="TAX_TYPE_MISMATCH", severity="error",
                             message="IGST charged on an intra-state supply; CGST + SGST should apply.",
                             fix="Amend the invoice, or issue a credit note and a new invoice."))
        if not intra and (cgst > 0 or sgst > 0):
            out.append(Issue(code="TAX_TYPE_MISMATCH", severity="error",
                             message="CGST/SGST charged on an inter-state supply; IGST should apply.",
                             fix="Amend the invoice."))
    if cgst != sgst:
        out.append(Issue(code="CGST_SGST_UNEQUAL", severity="warning", message=f"CGST ({cgst}) and SGST ({sgst}) are not equal."))

    # Math checks
    tv = inv.taxable_value
    if tv is None and inv.line_items:
        tv = sum(li.taxable_value or 0 for li in inv.line_items)
    tax = cgst + sgst + igst + (inv.cess or 0)
    if tv is not None and inv.total_amount is not None:
        if abs((tv + tax) - inv.total_amount) > max(1.0, 0.005 * inv.total_amount):   # ±₹1 / 0.5% rounding tolerance
            out.append(Issue(code="TOTAL_MISMATCH", severity="error",
                             message=f"Taxable ({tv}) + tax ({round(tax,2)}) = {round(tv+tax,2)}, but the invoice total is {inv.total_amount}.",
                             fix="Re-check the amounts."))
    if inv.line_items:
        li_sum = sum(li.taxable_value or 0 for li in inv.line_items)
        if inv.taxable_value and abs(li_sum - inv.taxable_value) > 1:
            out.append(Issue(code="LINE_SUM_MISMATCH", severity="warning",
                             message=f"Sum of line items ({li_sum}) does not match the header taxable value ({inv.taxable_value})."))

    # Rate slab + HSN checks (per line)
    valid_rates = RATES_LEGACY if (date and date < NEW_REGIME_DATE) else RATES_NEW
    for i, li in enumerate(inv.line_items, 1):
        if li.gst_rate is not None and li.gst_rate not in valid_rates:
            out.append(Issue(code="RATE_SLAB", severity="warning",
                             message=f"Line {i}: GST rate {li.gst_rate}% is not a standard slab for this invoice date.",
                             fix="Verify the rate for this HSN against the rate notification."))
        if li.hsn_sac and not re.fullmatch(r"\d{4}|\d{6}|\d{8}", li.hsn_sac):
            out.append(Issue(code="HSN_FORMAT", severity="warning", message=f"Line {i}: HSN/SAC '{li.hsn_sac}' is not 4, 6 or 8 digits long."))
        if not li.hsn_sac:
            out.append(Issue(code="HSN_MISSING", severity="warning", message=f"Line {i}: HSN/SAC is missing (mandatory depending on turnover)."))
        if li.gst_rate is not None and li.taxable_value and inv.taxable_value == li.taxable_value:
            expected = li.taxable_value * li.gst_rate / 100
            if tax and abs(expected - (cgst + sgst + igst)) > max(1.0, 0.01 * expected):
                out.append(Issue(code="TAX_AMOUNT_MISMATCH", severity="error",
                                 message=f"Line {i}: tax at {li.gst_rate}% should be ≈ {round(expected,2)}, but the invoice shows {round(cgst+sgst+igst,2)}."))

    if b2b and not inv.irn:
        out.append(Issue(code="IRN_ABSENT", severity="info",
                         message="No IRN/QR found. If the supplier's AATO exceeds the e-invoice threshold, a B2B invoice without an IRN is not valid.",
                         fix="Confirm with the supplier and verify on the e-invoice portal."))
    return out


# %% RAG — GST law knowledge base (CGST Act, rules, circulars, notifications)
def build_index(docs_dir: Path = DOCS_DIR, index_dir: Path = INDEX_DIR):
    from langchain_community.document_loaders import PyPDFLoader, TextLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    from langchain_openai import OpenAIEmbeddings

    docs = []
    for f in Path(docs_dir).glob("**/*"):
        if f.suffix.lower() == ".pdf":
            docs += PyPDFLoader(str(f)).load()
        elif f.suffix.lower() in {".txt", ".md"}:
            docs += TextLoader(str(f), encoding="utf-8").load()
    if not docs:
        raise RuntimeError(f"{docs_dir} is empty — add CGST Act / circular PDFs or .txt files there.")
    chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150).split_documents(docs)
    vs = FAISS.from_documents(chunks, OpenAIEmbeddings(model=EMBED_MODEL))
    vs.save_local(str(index_dir))
    return vs


_VS = None


def get_retriever(k: int = 4):
    global _VS
    if _VS is None:
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
        if Path(INDEX_DIR).exists():
            _VS = FAISS.load_local(str(INDEX_DIR), OpenAIEmbeddings(model=EMBED_MODEL), allow_dangerous_deserialization=True)
        else:
            _VS = build_index()
    return _VS.as_retriever(search_kwargs={"k": k})


def rag_answer(question: str) -> dict:
    docs = get_retriever().invoke(question)
    ctx = "\n\n".join(f"[{i+1}] ({d.metadata.get('source','?')} p{d.metadata.get('page','-')}) {d.page_content}" for i, d in enumerate(docs))
    msg = ("Answer the GST question ONLY from the context. Cite sources like [1]. "
           "If context insufficient, say so — don't guess.\n\nCONTEXT:\n" + ctx + f"\n\nQUESTION: {question}")
    return {"answer": get_llm().invoke(msg).content,
            "sources": [{"source": d.metadata.get("source"), "page": d.metadata.get("page")} for d in docs]}


# %% Multi-Agent System (LangGraph): Extractor -> Rule Validator -> Legal Researcher -> Advisor
class State(TypedDict, total=False):
    file_path: str
    raw_text: str
    invoice: dict
    issues: List[dict]
    legal_notes: str
    report: dict


def extractor_agent(s: State) -> State:
    text = s.get("raw_text") or ocr_document(s["file_path"])
    return {"raw_text": text, "invoice": extract_invoice(text).model_dump()}


def validator_agent(s: State) -> State:
    return {"issues": [i.model_dump() for i in validate_invoice(Invoice(**s["invoice"]))]}


def legal_researcher_agent(s: State) -> State:
    """Runs RAG only for the flagged issues plus a Sec 17(5) blocked-credit check."""
    inv = Invoice(**s["invoice"])
    queries = [f"{i['code']}: {i['message']}" for i in s["issues"] if i["severity"] != "info"][:4]
    items = "; ".join(li.description for li in inv.line_items[:5]) or "goods/services on invoice"
    queries.append(f"Is input tax credit blocked under section 17(5) for: {items}?")
    notes = []
    for q in queries:
        try:
            r = rag_answer(q)
            notes.append(f"Q: {q}\nA: {r['answer']}")
        except Exception as e:                       # keep the pipeline running even if the index is unavailable
            notes.append(f"Q: {q}\nA: (RAG unavailable: {e})")
            break
    return {"legal_notes": "\n\n".join(notes)}


ADVISOR_PROMPT = """You are a senior Indian GST compliance advisor. Write in clear, simple English.
Given the invoice, rule-check issues and legal notes, produce JSON with keys:
verdict ("ITC_ELIGIBLE" | "ITC_AT_RISK" | "ITC_BLOCKED"), summary (2-3 lines), actions (list of concrete steps, most urgent first),
supplier_followup (short message to send to supplier, or null).
Errors in issues => not ITC_ELIGIBLE. Don't invent law beyond the legal notes. Return ONLY JSON.

INVOICE: {inv}
ISSUES: {issues}
LEGAL NOTES: {notes}"""


def advisor_agent(s: State) -> State:
    resp = get_llm().invoke(ADVISOR_PROMPT.format(inv=json.dumps(s["invoice"]), issues=json.dumps(s["issues"]), notes=s.get("legal_notes", "")))
    txt = re.sub(r"^```(?:json)?|```$", "", resp.content.strip(), flags=re.M).strip()
    try:
        rep = json.loads(txt)
    except json.JSONDecodeError:
        rep = {"verdict": "ITC_AT_RISK", "summary": txt[:400], "actions": [], "supplier_followup": None}
    # Hard guard: the LLM cannot return "eligible" when any error exists
    if any(i["severity"] == "error" for i in s["issues"]) and rep.get("verdict") == "ITC_ELIGIBLE":
        rep["verdict"] = "ITC_AT_RISK"
    return {"report": rep}


def build_graph():
    from langgraph.graph import StateGraph, END
    g = StateGraph(State)
    g.add_node("extractor", extractor_agent)
    g.add_node("validator", validator_agent)
    g.add_node("legal_researcher", legal_researcher_agent)
    g.add_node("advisor", advisor_agent)
    g.set_entry_point("extractor")
    g.add_edge("extractor", "validator")
    g.add_edge("validator", "legal_researcher")
    g.add_edge("legal_researcher", "advisor")
    g.add_edge("advisor", END)
    return g.compile()


# %% Orchestration — end-to-end
_GRAPH = None


def analyze_invoice(file_path: str) -> dict:
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    out = _GRAPH.invoke({"file_path": file_path})
    return {"invoice": out["invoice"], "issues": out["issues"], "legal_notes": out.get("legal_notes"), "report": out["report"]}


def analyze_batch(paths: List[str]) -> List[dict]:
    """Analyze multiple invoices (e.g. all purchase invoices of one client) in one call."""
    return [{"file": p, **analyze_invoice(p)} for p in paths]


if __name__ == "__main__":
    import sys
    print(json.dumps(analyze_invoice(sys.argv[1]), indent=2, ensure_ascii=False))
