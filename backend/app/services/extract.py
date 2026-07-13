"""Extract plain text from an uploaded NDA file.

Dispatches on file type and returns newline-separated text that feeds the same
`segment()` -> Clause[] path the paste flow uses. .docx preserves paragraph and
table structure cleanly; PDF text extraction is best-effort (fine for text-based
PDFs, poor for scans — a scanned PDF needs OCR, out of scope here).
"""
from __future__ import annotations

import io

from fastapi import HTTPException


class UnsupportedFileType(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=415, detail=detail)


def _from_docx(content: bytes) -> str:
    from docx import Document as Docx

    doc = Docx(io.BytesIO(content))
    lines: list[str] = [p.text for p in doc.paragraphs]
    # include table cell text (some NDAs put schedules in tables)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _from_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages)


def extract_text(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        text = _from_docx(content)
    elif name.endswith(".pdf"):
        text = _from_pdf(content)
    elif name.endswith((".txt", ".md")):
        text = content.decode("utf-8", errors="replace")
    elif name.endswith(".doc"):
        raise UnsupportedFileType("legacy .doc isn't supported — save as .docx or PDF")
    else:
        raise UnsupportedFileType("upload a .docx, .pdf, .txt, or .md file")

    text = text.strip()
    if not text:
        raise UnsupportedFileType(
            "couldn't extract any text — if this is a scanned PDF it needs OCR (not supported yet)"
        )
    return text
