"""Tests for file text extraction (.docx / .pdf / .txt / unsupported)."""
import io

import pytest

from app.services.extract import UnsupportedFileType, extract_text

SAMPLE = "1. Term\nIn effect for sixty (60) months.\n2. Governing Law\nLaws of England and Wales."


def test_txt_passthrough():
    assert "sixty (60) months" in extract_text("nda.txt", SAMPLE.encode())


def test_docx_extraction():
    from docx import Document

    doc = Document()
    for line in SAMPLE.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    text = extract_text("nda.docx", buf.getvalue())
    assert "1. Term" in text and "England and Wales" in text


def test_pdf_extraction():
    reportlab = pytest.importorskip("reportlab")  # test-only dep; skip if absent
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for line in SAMPLE.split("\n"):
        c.drawString(72, y, line)
        y -= 20
    c.save()
    text = extract_text("nda.pdf", buf.getvalue())
    assert "Term" in text and "England and Wales" in text


def test_unsupported_type_raises():
    with pytest.raises(UnsupportedFileType):
        extract_text("nda.rtf", b"whatever")


def test_legacy_doc_rejected():
    with pytest.raises(UnsupportedFileType):
        extract_text("nda.doc", b"\xd0\xcf\x11\xe0")


def test_empty_extraction_raises():
    with pytest.raises(UnsupportedFileType):
        extract_text("nda.txt", b"   \n  ")
