from io import BytesIO

from pypdf import PdfWriter


def make_pdf() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    # Real article PDFs are comfortably larger than DOI2PDF's minimum sanity
    # threshold. PDF permits trailing whitespace after the final %%EOF marker.
    return buffer.getvalue() + b"\n" + b" " * 1024
