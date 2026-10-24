"""Text extraction + chunking for the Knowledge Base pipeline (§8.2)."""
import re

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware chunking with overlap, no chunk lost (§8.2).

    Markdown '## ' sections are treated as natural boundaries (FAQ quality),
    then paragraphs are packed into size-limited chunks with overlap.
    """
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    # Markdown headings are natural chunk boundaries
    if re.search(r"\n##? ", text):
        sections = [s.strip() for s in re.split(r"\n(?=##? )", text) if s.strip()]
    else:
        sections = [text]

    chunks: list[str] = []
    for section in sections:
        if len(section) <= size:
            chunks.append(section)
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
        current = ""
        for para in paragraphs:
            if len(para) > size:  # very long paragraph: hard split with overlap
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                start = 0
                while start < len(para):
                    chunks.append(para[start:start + size].strip())
                    start += size - overlap
                continue
            if len(current) + len(para) + 2 > size:
                if current.strip():
                    chunks.append(current.strip())
                current = ""
            current += para + "\n\n"
        if current.strip():
            chunks.append(current.strip())
    return [c for c in chunks if c]


# --------------------------------------------------------------------------- #
# Extractors
# --------------------------------------------------------------------------- #
def extract_pdf(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def extract_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n\n".join(parts)


def extract_xlsx(data: bytes) -> str:
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"# Feuille : {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def extract_csv(data: bytes) -> str:
    import csv
    import io

    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(" | ".join(row) for row in reader if row)


def extract_html(html: str) -> str:
    """Crude but dependency-free HTML → text, dropping scripts/styles/nav noise."""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as htmllib

    text = htmllib.unescape(text)
    return clean_text(text)
