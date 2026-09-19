from pathlib import Path
import json
import html
import re
import unicodedata
from io import BytesIO
from fastapi import FastAPI, Body, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pypdf import PdfReader
from docx import Document
try:
    import fitz
except ImportError:
    fitz = None

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "demo.json").read_text())

app = FastAPI(title="BMT TalentFlow AI", version="0.1.0")


def normalize_extracted_text(text: str) -> str:
    # Decode HTML entities, including numeric entities such as &#x20;.
    # Repeat because exported documents can contain nested entities.
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    # Normalize ligatures and other compatibility characters from PDF fonts.
    text = unicodedata.normalize("NFKC", text)
    # Remove Markdown/PDF escaping before punctuation and symbols.
    text = text.replace("\\\n", "\n")
    text = re.sub(r"\\([^\w\s])", r"\1", text)
    # Replace non-printing and non-breaking characters with regular spaces.
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = "".join(character if character in "\n\t" or character.isprintable() else " " for character in text)
    # Clean horizontal whitespace without destroying paragraph boundaries.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # PDF extractors sometimes put the bullet on a separate line.
    text = re.sub(r"(?m)^[ \t]*(•|·|\-)\s*\n\s*", r"\1 ", text)
    # Also normalize escaped list markers that may survive in source PDFs.
    text = re.sub(r"(?m)^\s*\\-\s+", "- ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_documents(text: str) -> list[dict]:
    """Split a combined application package into recognizable document sections."""
    markers = []
    cv_match = re.search(r"(?m)^Dr\.\s+Matthias Droth\s*$", text)
    reference_match = re.search(r"(?m)^Arbeitszeugnis für\b", text)
    if cv_match and cv_match.start() > 0:
        markers.append((0, cv_match.start(), "Anschreiben", "Bewerbungsanschreiben"))
        if reference_match and reference_match.start() > cv_match.start():
            markers.append((cv_match.start(), reference_match.start(), "Lebenslauf", "Lebenslauf"))
            markers.append((reference_match.start(), len(text), "Arbeitszeugnis", "Arbeitszeugnis"))
        else:
            markers.append((cv_match.start(), len(text), "Lebenslauf", "Lebenslauf"))
    elif reference_match:
        markers.append((0, reference_match.start(), "Bewerbungsunterlagen", "Bewerbungsunterlagen"))
        markers.append((reference_match.start(), len(text), "Arbeitszeugnis", "Arbeitszeugnis"))
    else:
        markers.append((0, len(text), "Bewerbungsunterlagen", "Bewerbungsunterlagen"))
    return [
        {"type": kind, "title": title, "text": normalize_extracted_text(text[start:end])}
        for start, end, kind, title in markers
        if normalize_extracted_text(text[start:end])
    ]


def extract_candidate_name(text: str) -> str | None:
    match = re.search(r"(?mi)^\s*((?:Dr\.\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'’-]+\s+[A-ZÄÖÜ][\wÄÖÜäöüß'’-]+)\s*$", text)
    return match.group(1).strip() if match else None


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "talentflow-ai", "mode": "demo"}


@app.get("/api/job")
def get_job():
    return DATA["job"]


@app.get("/api/candidate")
def get_candidate():
    return DATA["candidate"]


def extract_document_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        if fitz is not None:
            document = fitz.open(stream=content, filetype="pdf")
            pages = []
            for page in document:
                blocks = page.get_text("blocks")
                ordered = sorted(blocks, key=lambda block: (round(block[1] / 4) * 4, block[0]))
                pages.append("\n".join(block[4].strip() for block in ordered if block[4].strip()))
            text = "\n\n".join(pages).strip()
            if text:
                return text
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if extension == ".docx":
        document = Document(BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    raise HTTPException(status_code=400, detail="Bitte nur PDF- oder DOCX-Dateien hochladen.")


@app.post("/api/candidate/upload")
async def upload_candidate_document(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Die Datei darf maximal 10 MB groß sein.")
    text = normalize_extracted_text(extract_document_text(file.filename or "upload", content))
    if not text:
        raise HTTPException(status_code=422, detail="Aus der Datei konnte kein Text extrahiert werden.")
    return {
        "status": "extracted",
        "filename": file.filename,
        "characters": len(text),
        "preview": text[:4000],
        "text": text,
        "documents": classify_documents(text),
        "candidate_name": extract_candidate_name(text),
        "message": "Dokument erfolgreich gelesen. Die Analyse kann jetzt gestartet werden."
    }


@app.post("/api/analyze")
def analyze(payload: dict = Body(default={} )):
    document_text = (payload.get("document_text") or "").lower()
    has_document = bool(document_text.strip())
    signals = {
        "API- und Systemintegration": ["api", "rest", "integration", "schnittstelle", "middleware"],
        "Python": ["python", "fastapi", "django", "pandas"],
        "GenAI- und LLM-APIs": ["genai", "generative ai", "llm", "openai", "deepseek", "langchain"],
        "SAP- oder ERP-Erfahrung": ["sap", "s/4hana", "erp", "successfactors"],
        "Cloud-Dienste": ["azure", "aws", "gcp", "cloud"],
        "OAuth und API-Sicherheit": ["oauth", "oauth2", "api-key", "authentication", "authentifizierung"]
    }
    evidence_defaults = {
        "API- und Systemintegration": "Keine passende Evidenz im Dokument gefunden.",
        "Python": "Keine passende Evidenz im Dokument gefunden.",
        "GenAI- und LLM-APIs": "Keine passende Evidenz im Dokument gefunden.",
        "SAP- oder ERP-Erfahrung": "Keine passende Evidenz im Dokument gefunden.",
        "Cloud-Dienste": "Keine passende Evidenz im Dokument gefunden.",
        "OAuth und API-Sicherheit": "Keine passende Evidenz im Dokument gefunden."
    }
    matched = []
    for requirement, keywords in signals.items():
        found = [keyword for keyword in keywords if keyword in document_text]
        score = min(96, 62 + len(found) * 8) if found else 35
        evidence = f"Erkannte Begriffe: {', '.join(found[:3])}." if found else evidence_defaults[requirement]
        matched.append({"requirement": requirement, "evidence": evidence, "score": score})
    score = round(sum(item["score"] for item in matched) / len(matched)) if has_document else 89
    gaps = [
        f"Für folgende Anforderung wurde keine eindeutige Evidenz gefunden: {item['requirement']}."
        for item in matched if item["score"] == 35
    ]
    if not gaps:
        gaps = ["Erfahrung mit GraphQL und iPaaS sollte im Gespräch vertieft werden."]
    recommendation = "Zum technischen Erstgespräch einladen" if score >= 70 else "Profil im Fachgespräch vertiefen"
    return {
        "status": "completed",
        "score": score,
        "confidence": 0.84 if has_document else 0.91,
        "recommendation": recommendation,
        "matched": matched,
        "gaps": gaps[:3],
        "questions": [
            "Wie würden Sie einen LLM-Service sicher an SAP S/4HANA anbinden?",
            "Wie behandeln Sie Timeouts, Retries und Rate Limits bei GenAI-APIs?",
            "Wie stellen Sie Nachvollziehbarkeit und Datenschutz bei Bewerberdaten sicher?"
        ],
        "audit": {"model": "rules-provider", "prompt_version": "v0.2", "source": "uploaded-document" if has_document else "mock-sap"}
    }


@app.post("/api/status")
def update_status():
    return {"status": "saved", "system": "mock-sap", "message": "Recruiting-Status aktualisiert"}


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/{path:path}")
def static_files(path: str):
    file = ROOT / "frontend" / path
    if not file.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(file)
