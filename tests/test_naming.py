from pathlib import Path

from doi2pdf.naming import build_pdf_path


def test_legacy_zotero_filename(tmp_path: Path):
    path = build_pdf_path(
        tmp_path, zotero_key="9ET75JMH", author="Vaswani", year="2017", doi="10.1/x"
    )
    assert path.name == "9ET75JMH_Vaswani_2017.pdf"


def test_translator_metadata_and_collision(tmp_path: Path):
    metadata = {
        "title": "A useful paper",
        "date": "2026-03-01",
        "creators": [{"creatorType": "author", "lastName": "陳"}],
    }
    first = build_pdf_path(tmp_path, zotero_key="ABCDEFGH", metadata=metadata)
    first.write_bytes(b"existing")
    second = build_pdf_path(tmp_path, zotero_key="ABCDEFGH", metadata=metadata)
    assert first.name == "ABCDEFGH_陳_2026.pdf"
    assert second.name == "ABCDEFGH_陳_2026_2.pdf"
