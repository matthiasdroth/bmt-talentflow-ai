from pathlib import Path
import json
import html
import re
import shutil
import subprocess
import unicodedata
from io import BytesIO
from statistics import mean
from fastapi import FastAPI, Body, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pypdf import PdfReader
from docx import Document
from .integrations import MockSapClient, RulesGenAIProvider
try:
    import fitz
except ImportError:
    fitz = None

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "demo.json").read_text())

app = FastAPI(title="BMT TalentFlow AI", version="0.1.0")
sap_client = MockSapClient(DATA)
genai_provider = RulesGenAIProvider()


def repair_ocr_errors(text: str) -> str:
    """Correct conservative, recurring OCR/PDF line-break errors."""
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"(?i)\b(?:al|a1)\s+(?=engineer|lab|use cases)\b", "AI ", text)
    text = re.sub(r"(?i)\b(?:tatig|tätig)\b", "tätig", text)
    text = re.sub(r"(?i)\barbeitsverhaltnis\b", "Arbeitsverhältnis", text)
    corrections = {
        "Cails": "Calls",
        "verschiedender": "verschiedener",
        "transkriptierten Calls": "transkribierten Calls",
        "Uber": "über",
        "Forderungsmanageinent": "Forderungsmanagement",
    }
    for wrong, right in corrections.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)

    # OCR often turns bullets into unrelated glyphs. Restrict this to the
    # beginning of a line so meaningful asterisks in prose remain untouched.
    text = re.sub(r"(?m)^\s*[°¢©*]\s+", "• ", text)

    # Remove recurring scan artefacts from letterheads and legal footers.
    noise_patterns = (
        r"^\s*(?:en|COED|EBDIU)\s*$",
        r"^\s*(?:USt-Id-Nummer|USt-IdNr\.?|Steuernummer|Handelsregister|Registergericht|Sitz der Gesellschaft)\b.*$",
        r"^\s*(?:Registriertes Inkasso-Unternehmen|nach §\s*10|Deutsche Bank|IBAN:|BIC:|Mitglied(?:sverband)? Deutscher)\b.*$",
    )
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text


def preprocess_ocr_image(page):
    """Render a page and improve contrast before sending it to OCR."""
    pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    raw_png = pixmap.tobytes("png")
    image_tool = shutil.which("magick")
    if not image_tool:
        return raw_png
    try:
        result = subprocess.run(
            [image_tool, "png:-", "-colorspace", "Gray", "-auto-level",
             "-contrast-stretch", "0x5%", "-sharpen", "0x1", "png:-"],
            input=raw_png,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
        return result.stdout or raw_png
    except (OSError, subprocess.TimeoutExpired):
        return raw_png


def ocr_page(page) -> tuple[str, float]:
    """Run optional local OCR and return text plus average word confidence."""
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return "", 0.0
    try:
        image = preprocess_ocr_image(page)
        tsv_result = subprocess.run(
            [tesseract, "stdin", "stdout", "-l", "deu+eng", "--psm", "3", "tsv"],
            input=image,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        confidences = []
        lines = {}
        for line in tsv_result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            fields = line.split("\t")
            if len(fields) >= 12 and fields[11].strip():
                line_key = tuple(fields[index] for index in (2, 3, 4))
                lines.setdefault(line_key, []).append(fields[11].strip())
                try:
                    confidence = float(fields[10])
                    if confidence >= 0:
                        confidences.append(confidence)
                except ValueError:
                    pass
        text = "\n".join(" ".join(words) for words in lines.values()).strip()
        return text, round(mean(confidences), 1) if confidences else 0.0
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return "", 0.0


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
    text = repair_ocr_errors(text)
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
    """Split a combined application package into recognizable document sections.

    A reference is optional and may occur zero, one, or multiple times.  The
    heading is used as the boundary so that each employment reference gets
    its own section instead of being merged with the previous one.
    """
    markers = []
    cv_match = re.search(r"(?m)^Dr\.\s+Matthias Droth\s*$", text)
    # PDF extraction does not always preserve the visual line break before a
    # certificate heading.  Therefore the heading may be embedded in a line
    # with a company name or date.  Match the heading itself rather than
    # requiring the whole line to consist of it.
    reference_matches = list(re.finditer(
        r"(?i)(?<!\w)(?:Arbeitszeugnis|Zwischenzeugnis)(?:\s+für\b[^\n]*|[ \t]*:?[ \t]*(?=\n|$))",
        text,
    ))

    # Some employers title a reference only as "ZEUGNIS".  Keep those apart
    # from academic certificates by requiring employment-related language in
    # the following text.
    employment_terms = (
        "arbeitsverhältnis", "als software engineer", "als ai engineer",
        "in unserem unternehmen tätig", "ausscheiden", "arbeitszeugnis",
    )
    for heading in re.finditer(r"(?mi)^.*\bZEUGNIS\b.*$", text):
        context = text[heading.start():heading.start() + 1200].lower()
        if any(term in context for term in employment_terms):
            reference_matches.append(heading)

    # The explicit and generic heading patterns can identify the same line.
    # Deduplicate nearby matches and keep the document order.
    reference_matches = sorted(reference_matches, key=lambda match: match.start())
    unique_references = []
    for reference in reference_matches:
        if not unique_references or reference.start() - unique_references[-1].start() > 20:
            unique_references.append(reference)
    reference_matches = unique_references
    first_reference = reference_matches[0] if reference_matches else None

    if cv_match and cv_match.start() > 0:
        markers.append((0, cv_match.start(), "Anschreiben", "Bewerbungsanschreiben"))
        if first_reference and first_reference.start() > cv_match.start():
            markers.append((cv_match.start(), first_reference.start(), "Lebenslauf", "Lebenslauf"))
        else:
            markers.append((cv_match.start(), len(text), "Lebenslauf", "Lebenslauf"))
    elif first_reference:
        markers.append((0, first_reference.start(), "Bewerbungsunterlagen", "Bewerbungsunterlagen"))
    else:
        markers.append((0, len(text), "Bewerbungsunterlagen", "Bewerbungsunterlagen"))

    education_match = re.search(
        r"(?mi)^(?:The University of Konstanz confers|.*Diplomprüfung.*|.*allgemeinen Hochschulreife.*)$",
        text,
    )
    for index, reference in enumerate(reference_matches, start=1):
        next_reference = reference_matches[index].start() if index < len(reference_matches) else len(text)
        end = next_reference
        if education_match and education_match.start() > reference.start():
            end = min(end, education_match.start())
        label = "Arbeitszeugnis" if len(reference_matches) == 1 else f"Arbeitszeugnis {index}"
        markers.append((reference.start(), end, label, label))

    if education_match:
        markers.append((education_match.start(), len(text), "Weitere Zeugnisse", "Weitere Zeugnisse"))

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
    return {
        "status": "ok",
        "service": "talentflow-ai",
        "mode": "demo",
        "integrations": {"sap": "mock", "genai": genai_provider.provider_name},
    }


@app.get("/api/job")
def get_job():
    return sap_client.get_job()


@app.get("/api/candidate")
def get_candidate():
    return sap_client.get_candidate()


def extract_document_text(filename: str, content: bytes) -> tuple[str, int, int, float]:
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        if fitz is not None:
            document = fitz.open(stream=content, filetype="pdf")
            pages = []
            ocr_pages = 0
            ocr_confidences = []
            fallback_reader = None
            for page_index, page in enumerate(document):
                blocks = page.get_text("blocks")
                ordered = sorted(blocks, key=lambda block: (round(block[1] / 4) * 4, block[0]))
                page_text = "\n".join(block[4].strip() for block in ordered if block[4].strip())

                # Some PDF pages expose no usable blocks even though their
                # text layer is readable. Try the page-level extractor before
                # falling back to pypdf for that specific page.
                if not page_text:
                    page_text = page.get_text("text", sort=True).strip()
                if not page_text:
                    if fallback_reader is None:
                        fallback_reader = PdfReader(BytesIO(content))
                    page_text = (fallback_reader.pages[page_index].extract_text() or "").strip()
                if not page_text:
                    page_text, confidence = ocr_page(page)
                    if page_text:
                        ocr_pages += 1
                        if confidence:
                            ocr_confidences.append(confidence)
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages).strip()
            if text:
                return text, len(document), ocr_pages, round(mean(ocr_confidences), 1) if ocr_confidences else 0.0
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip(), len(reader.pages), 0, 0.0
    if extension == ".docx":
        document = Document(BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip(), 0, 0, 0.0
    raise HTTPException(status_code=400, detail="Bitte nur PDF- oder DOCX-Dateien hochladen.")


@app.post("/api/candidate/upload")
async def upload_candidate_document(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Die Datei darf maximal 10 MB groß sein.")
    text, page_count, ocr_pages, ocr_confidence = extract_document_text(file.filename or "upload", content)
    text = normalize_extracted_text(text)
    if not text:
        raise HTTPException(status_code=422, detail="Aus der Datei konnte kein Text extrahiert werden.")
    return {
        "status": "extracted",
        "filename": file.filename,
        "characters": len(text),
        "pages": page_count,
        "ocr": {"pages": ocr_pages, "confidence": ocr_confidence},
        "preview": text[:4000],
        "text": text,
        "documents": classify_documents(text),
        "candidate_name": extract_candidate_name(text),
        "message": "Dokument erfolgreich gelesen. Die Analyse kann jetzt gestartet werden."
    }


@app.post("/api/analyze")
def analyze(payload: dict = Body(default={} )):
    return genai_provider.analyze(payload.get("document_text") or "", sap_client.get_job())


@app.post("/api/status")
def update_status():
    return sap_client.update_status("analysis-completed")


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/{path:path}")
def static_files(path: str):
    file = ROOT / "frontend" / path
    if not file.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(file)
