import http.server
import socketserver
import threading

from doi2pdf.http import PDF_MAGIC, HttpClient


PDF_BYTES = PDF_MAGIC + b" test\n" + b"0" * 2048


def _serve(responses):
    """Serve one (status, body) per request, repeating the last once exhausted."""
    calls: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            index = min(len(calls), len(responses) - 1)
            status, body = responses[index]
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, calls


def test_fetch_pdf_retries_on_503_then_succeeds():
    server, calls = _serve([(503, b""), (503, b""), (200, PDF_BYTES)])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=3)
        content, status = client.fetch_pdf(url)
        assert status == "pdf"
        assert content == PDF_BYTES
        assert len(calls) == 3
    finally:
        server.shutdown()


def test_fetch_pdf_does_not_retry_client_errors():
    server, calls = _serve([(404, b"not found")])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=3)
        content, status = client.fetch_pdf(url)
        assert status == "http_404"
        assert content is None
        assert len(calls) == 1
    finally:
        server.shutdown()


def test_fetch_pdf_gives_up_after_max_retries_exhausted():
    server, calls = _serve([(503, b"")])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=2)
        content, status = client.fetch_pdf(url)
        assert content is None
        assert status.startswith("request_error:") or status == "http_503"
        assert len(calls) == 3  # first attempt + 2 retries
    finally:
        server.shutdown()


def test_max_retries_configures_adapter():
    client = HttpClient("test@example.org", max_retries=5)
    adapter = client.session.get_adapter("https://example.org")
    assert adapter.max_retries.total == 5
    assert set(adapter.max_retries.status_forcelist) == {429, 500, 502, 503, 504}
    assert adapter.max_retries.allowed_methods == frozenset({"GET"})


def test_max_retries_zero_leaves_default_adapter():
    client = HttpClient("test@example.org", max_retries=0)
    adapter = client.session.get_adapter("https://example.org")
    assert not adapter.max_retries.status_forcelist
