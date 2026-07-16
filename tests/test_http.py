import http.server
import socketserver
import threading

from doi2pdf.http import MAX_PDF_BYTES, HttpClient, looks_like_challenge_text, pdf_validation_status, read_bounded_response
from tests._pdf import make_pdf


PDF_BYTES = make_pdf()


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


def _serve_declared_size(size: int, body: bytes = b""):
    calls: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if body:
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
        # These tests deliberately target loopback, so the SSRF guard (on by
        # default; see test_ssrf_* below) must be disabled here.
        client = HttpClient("test@example.org", timeout=5, max_retries=3, block_private_hosts=False)
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
        client = HttpClient("test@example.org", timeout=5, max_retries=3, block_private_hosts=False)
        content, status = client.fetch_pdf(url)
        assert status == "http_404"
        assert content is None
        assert len(calls) == 1
    finally:
        server.shutdown()


def test_fetch_pdf_reports_challenge_pages_explicitly():
    server, calls = _serve([(200, b"Performing security verification")])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=0, block_private_hosts=False)
        content, status = client.fetch_pdf(url)
        assert content is None
        assert status == "cf_challenge"
        assert len(calls) == 1
    finally:
        server.shutdown()


def test_fetch_pdf_rejects_declared_oversize_before_reading_body():
    server, calls = _serve_declared_size(MAX_PDF_BYTES + 1)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=0, block_private_hosts=False)
        content, status = client.fetch_pdf(url)
        assert content is None
        assert status == "pdf_too_large"
        assert len(calls) == 1
    finally:
        server.shutdown()


def test_pdf_validation_rejects_truncated_and_header_only_files():
    assert pdf_validation_status(b"%PDF-1.7\n" + b"x" * 2048) == "pdf_missing_eof"
    assert pdf_validation_status(b"%PDF-1.7\n") == "pdf_too_small"
    assert pdf_validation_status(b"<html>not a PDF</html>") == "not_pdf"
    assert pdf_validation_status(PDF_BYTES) == "pdf"


def test_stream_limit_stops_after_crossing_bound_without_content_length():
    class ChunkedResponse:
        headers = {}

        @staticmethod
        def iter_content(chunk_size):
            yield b"12345"
            yield b"67890"
            raise AssertionError("reader should stop immediately after exceeding the bound")

    content, status = read_bounded_response(ChunkedResponse(), maximum=8)
    assert content is None
    assert status == "pdf_too_large"


def test_pdf_validation_rejects_structurally_invalid_pdf_with_eof_marker():
    content = b"%PDF-1.7\n" + b"x" * 2048 + b"\n%%EOF\n"
    assert pdf_validation_status(content) == "pdf_invalid_structure"


def test_normal_cloudflare_asset_reference_is_not_a_challenge():
    assert not looks_like_challenge_text('<script src="https://static.cloudflareinsights.com/beacon.js"></script>')
    assert looks_like_challenge_text('<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>')


def test_fetch_pdf_gives_up_after_max_retries_exhausted():
    server, calls = _serve([(503, b"")])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=2, block_private_hosts=False)
        content, status = client.fetch_pdf(url)
        assert content is None
        assert status.startswith("request_error:") or status == "http_503"
        assert len(calls) == 3  # first attempt + 2 retries
    finally:
        server.shutdown()


def test_ssrf_guard_blocks_loopback_by_default():
    server, calls = _serve([(200, PDF_BYTES)])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/paper.pdf"
        client = HttpClient("test@example.org", timeout=5, max_retries=0)  # block_private_hosts defaults True
        content, status = client.fetch_pdf(url)
        assert content is None
        assert status.startswith("request_error:")
        assert calls == []  # the connection was refused before it ever reached the server
    finally:
        server.shutdown()


def test_ssrf_guard_blocks_a_public_looking_hostname_that_resolves_privately(monkeypatch):
    # This is the actual attack this guard defends against: a hostname that
    # looks like a normal public API (as every OA-index candidate URL does)
    # but whose DNS resolves to an internal address (DNS rebinding, or a
    # compromised/malicious index). The check must key off the resolved IP,
    # not the hostname string.
    import socket

    import requests

    from doi2pdf.http import _PublicHostOnlyAdapter

    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "looks-like-a-public-api.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    adapter = _PublicHostOnlyAdapter()
    request = requests.Request("GET", "http://looks-like-a-public-api.example/paper.pdf").prepare()
    try:
        adapter.send(request)
        assert False, "expected a ConnectionError"
    except requests.exceptions.ConnectionError:
        pass


def test_is_public_ip_classifies_addresses():
    from doi2pdf.http import _is_public_ip

    assert _is_public_ip("93.184.216.34") is True  # example.com, public
    assert _is_public_ip("127.0.0.1") is False
    assert _is_public_ip("10.0.0.5") is False
    assert _is_public_ip("192.168.1.1") is False
    assert _is_public_ip("169.254.1.1") is False
    assert _is_public_ip("::1") is False


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
