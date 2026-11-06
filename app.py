import os, shutil, tempfile
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from pipeline import analyze_invoice, rag_answer, build_index

app = FastAPI(title="GST Compliance Copilot", version="1.0")
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


class Ask(BaseModel):
    question: str


def _save(f: UploadFile) -> str:
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type {ext}. Allowed: {sorted(ALLOWED)}")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    shutil.copyfileobj(f.file, tmp); tmp.close()
    return tmp.name


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(file: UploadFile = File(...)):
    path = _save(file)
    try:
        return analyze_invoice(path)
    finally:
        os.unlink(path)


@app.post("/analyze-batch")
def analyze_batch_ep(files: List[UploadFile] = File(...)):
    results = []
    for f in files:
        path = _save(f)
        try:
            results.append({"file": f.filename, **analyze_invoice(path)})
        except Exception as e:
            results.append({"file": f.filename, "error": str(e)})
        finally:
            os.unlink(path)
    summary = {}
    for r in results:
        v = r.get("report", {}).get("verdict", "ERROR")
        summary[v] = summary.get(v, 0) + 1
    return {"summary": summary, "results": results}


@app.post("/ask")
def ask(body: Ask):
    return rag_answer(body.question)


@app.post("/reindex")
def reindex():
    build_index()
    return {"status": "reindexed"}
