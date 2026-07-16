from doi2pdf.publisher_routes import (
    ROUTES,
    citation_pdf_url,
    lww_article_details,
    lww_signed_pdf_url,
    ovid_viewer_pdf_url,
    rewrite_for_proxy,
    route_group_for,
    route_for,
    template_url,
)


def test_complete_original_route_registry_is_present():
    assert len(ROUTES) == 23
    assert route_for("10.1056/NEJMoa1").kind == "tpl"
    assert route_for("10.1136/bmj.1").headful is True
    assert route_for("10.1097/ABC.1").kind == "lww"
    assert template_url(route_for("10.1111/test"), "10.1111/test") == "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/test?download=true"
    assert route_group_for("10.1056/NEJMoa1") == "nejm"
    assert route_group_for("10.1016/j.test") == "10.1016"


def test_proxy_rewrite_and_meta_extraction():
    assert rewrite_for_proxy("https://www.nejm.org/doi/pdf/10.1056/x", "proxy.example.edu") == "https://www-nejm-org.proxy.example.edu/doi/pdf/10.1056/x"
    document = '<html><meta name="citation_pdf_url" content="https://example.org/a.pdf?a=1&amp;b=2"></html>'
    assert citation_pdf_url(document) == "https://example.org/a.pdf?a=1&b=2"


def test_lww_and_ovid_signed_url_parsers():
    article = "<script>an='12345678-123456789-12345'</script>"
    assert lww_article_details(article, "https://journals-lww-com.proxy/journal/fulltext/x") == ("12345678-123456789-12345", "journal")
    assert lww_signed_pdf_url('{"pdfDownloadDetails":{"pdfUrl":"https:\\/\\/pdfs.example\\/x.pdf"}}') == "https://pdfs.example/x.pdf"
    assert ovid_viewer_pdf_url("https://oce/pdfviewer/web/viewer.html?file=https%3A%2F%2Fassets.example%2Fa.pdf") == "https://assets.example/a.pdf"
