"""Phase 5 A.4: PDF/attachment failure classification. classify_pdf_failure
is only called when the fast-path byte-scan (jpeg_from_pdf) finds no
embedded JPEG marker - these tests build small real PDFs with PyMuPDF
(itself the library doing the classification) covering each failure mode
the phase asks to distinguish."""
import io

import pymupdf as fitz
import pytest
from PIL import Image

from scripts.pipeline import MIN_IMAGE_DIM, classify_pdf_failure, jpeg_from_pdf


def _png_bytes(w, h, color=(200, 50, 50)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, format='PNG')
    return buf.getvalue()


def _pdf_with_image(w, h, page_size=(300, 300)):
    doc = fitz.open()
    page = doc.new_page(width=page_size[0], height=page_size[1])
    page.insert_image(fitz.Rect(0, 0, min(w, page_size[0]), min(h, page_size[1])), stream=_png_bytes(w, h))
    raw = doc.tobytes()
    doc.close()
    return raw


def _pdf_text_only():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'A sanction letter with no photograph attached.')
    raw = doc.tobytes()
    doc.close()
    return raw


def _pdf_encrypted():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'Password protected.')
    buf = io.BytesIO()
    doc.save(buf, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner-secret', user_pw='user-secret')
    doc.close()
    return buf.getvalue()


def test_corrupt_pdf_is_classified_as_corrupt_document():
    jpeg, category, detail = classify_pdf_failure(b'%PDF-1.4\ngarbage not a real pdf structure')
    assert jpeg is None
    assert category == 'corrupt_document'
    assert detail


def test_text_only_pdf_is_classified_as_pdf_without_extractable_image():
    raw = _pdf_text_only()
    assert jpeg_from_pdf(raw) is None  # fast-path correctly finds nothing
    jpeg, category, detail = classify_pdf_failure(raw)
    assert jpeg is None
    assert category == 'pdf_without_extractable_image'


def test_encrypted_pdf_is_classified_as_encrypted_document():
    raw = _pdf_encrypted()
    jpeg, category, detail = classify_pdf_failure(raw)
    assert jpeg is None
    assert category == 'encrypted_document'


def test_pdf_with_only_a_tiny_embedded_raster_is_document_page_not_a_photo():
    # A logo/letterhead-sized raster - below MIN_IMAGE_DIM - must never be
    # treated as photographic evidence (Phase 5 A.4 / Phase 4 mandatory
    # safeguard: "never declare a document page as a completion photograph").
    raw = _pdf_with_image(40, 40, page_size=(300, 300))
    jpeg, category, detail = classify_pdf_failure(raw)
    assert jpeg is None
    assert category == 'document_page'


def test_pdf_with_a_real_sized_embedded_raster_is_recovered_as_a_photo():
    raw = _pdf_with_image(MIN_IMAGE_DIM + 50, MIN_IMAGE_DIM + 50, page_size=(400, 400))
    jpeg, category, detail = classify_pdf_failure(raw)
    assert category == 'recovered'
    assert jpeg is not None
    with Image.open(io.BytesIO(jpeg)) as im:
        im.load()
        assert min(im.width, im.height) >= MIN_IMAGE_DIM
        assert im.format == 'JPEG'
