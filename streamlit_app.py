"""Streamlit UI — run: streamlit run streamlit_app.py
Default: imports the pipeline directly. Enter an API URL in the sidebar to use the deployed FastAPI service (AWS) instead."""
import os, tempfile, json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="GST Compliance Copilot", page_icon="🧾", layout="wide")

VERDICT_UI = {"ITC_ELIGIBLE": ("✅ ITC Eligible", "success"), "ITC_AT_RISK": ("⚠️ ITC At Risk", "warning"), "ITC_BLOCKED": ("⛔ ITC Blocked", "error")}
SEV_ICON = {"error": "🔴 error", "warning": "🟠 warning", "info": "🔵 info"}

with st.sidebar:
    st.title("🧾 GST Copilot")
    api_url = st.text_input("API URL (optional)", placeholder="http://<app-runner-url>", help="Leave empty to use the local pipeline")
    if not api_url and not os.getenv("OPENAI_API_KEY"):
        key = st.text_input("OPENAI_API_KEY", type="password")
        if key:
            os.environ["OPENAI_API_KEY"] = key
    st.caption("Sample invoices are in the `samples/` folder (run `python generate_samples.py`).")


def run_analyze(name: str, data: bytes) -> dict:
    if api_url:
        import requests
        r = requests.post(api_url.rstrip("/") + "/analyze", files={"file": (name, data)}, timeout=180)
        r.raise_for_status()
        return r.json()
    from pipeline import analyze_invoice
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as f:
        f.write(data)
    try:
        return analyze_invoice(f.name)
    finally:
        os.unlink(f.name)


def render(res: dict):
    rep, issues, inv = res["report"], res["issues"], res["invoice"]
    label, kind = VERDICT_UI.get(rep.get("verdict"), (rep.get("verdict", "?"), "info"))
    getattr(st, kind)(f"**{label}** — {rep.get('summary', '')}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Errors", sum(i["severity"] == "error" for i in issues))
    c2.metric("Warnings", sum(i["severity"] == "warning" for i in issues))
    c3.metric("Invoice total", f"₹{inv.get('total_amount') or 0:,.2f}")
    if issues:
        st.subheader("Compliance issues")
        st.dataframe(pd.DataFrame([{"Severity": SEV_ICON[i["severity"]], "Code": i["code"], "Issue": i["message"], "Fix": i.get("fix") or ""} for i in issues]),
                     width="stretch", hide_index=True)
    else:
        st.success("No issues found by the rule checks.")
    if rep.get("actions"):
        st.subheader("Action items")
        for a in rep["actions"]:
            st.markdown(f"- {a}")
    if rep.get("supplier_followup"):
        st.subheader("Message to send to the supplier")
        st.code(rep["supplier_followup"], language=None)
    with st.expander("Extracted invoice data"):
        st.json(inv)
    if res.get("legal_notes"):
        with st.expander("Legal research (RAG)"):
            st.text(res["legal_notes"])


tab1, tab2, tab3 = st.tabs(["📄 Single invoice", "📚 Batch", "💬 Ask GST law"])

with tab1:
    up = st.file_uploader("Upload an invoice (PDF/PNG/JPG)", type=["pdf", "png", "jpg", "jpeg"], key="one")
    samples = sorted(Path("samples").glob("*.[pP][dD][fF]")) + sorted(Path("samples").glob("*.png"))
    pick = st.selectbox("...or pick a sample", ["—"] + [p.name for p in samples])
    if st.button("Analyze", type="primary"):
        if up:
            name, data = up.name, up.getvalue()
        elif pick != "—":
            name, data = pick, (Path("samples") / pick).read_bytes()
        else:
            st.stop()
        with st.spinner("OCR → extraction → rules → legal research → advice..."):
            try:
                render(run_analyze(name, data))
            except Exception as e:
                st.error(f"Failed: {e}")

with tab2:
    files = st.file_uploader("Multiple invoices", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True, key="many")
    if st.button("Analyze all") and files:
        rows, results = [], {}
        bar = st.progress(0.0)
        for n, f in enumerate(files, 1):
            try:
                res = run_analyze(f.name, f.getvalue()); results[f.name] = res
                rows.append({"File": f.name, "Verdict": res["report"].get("verdict"), "Errors": sum(i["severity"] == "error" for i in res["issues"]),
                             "Warnings": sum(i["severity"] == "warning" for i in res["issues"]), "Total ₹": res["invoice"].get("total_amount")})
            except Exception as e:
                rows.append({"File": f.name, "Verdict": f"ERROR: {e}", "Errors": None, "Warnings": None, "Total ₹": None})
            bar.progress(n / len(files))
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False), "gst_batch_report.csv", "text/csv")
        for name, res in results.items():
            with st.expander(name):
                render(res)

with tab3:
    q = st.text_input("Ask a GST question", placeholder="Is ITC allowed on employee food expenses?")
    if st.button("Ask") and q:
        with st.spinner("Searching GST law..."):
            try:
                if api_url:
                    import requests
                    r = requests.post(api_url.rstrip("/") + "/ask", json={"question": q}, timeout=120); r.raise_for_status(); out = r.json()
                else:
                    from pipeline import rag_answer
                    out = rag_answer(q)
                st.markdown(out["answer"])
                st.caption("Sources: " + ", ".join(f"{s['source']} (p{s['page']})" for s in out["sources"]))
            except Exception as e:
                st.error(f"Failed: {e} — have you added documents to data/gst_docs/?")
