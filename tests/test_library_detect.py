import pytest

from doi2pdf.library_detect import detect_library_link


def test_detects_openathens_and_discards_target():
    result = detect_library_link("https://go.openathens.net/redirector/example.edu?url=https%3A%2F%2Fpublisher.example%2Fpaper%3Ftoken%3Dsecret")
    assert result["kind"] == "openathens"
    assert result["updates"] == {"OPENATHENS_REDIRECTOR_PREFIX": "https://go.openathens.net/redirector/example.edu?url="}
    assert "token" not in str(result["updates"])


def test_detects_ezproxy_starting_point_and_suffix():
    prefix = detect_library_link("https://login.example.edu/login?url=https://publisher.example/article")
    assert prefix["updates"] == {"EZPROXY_PREFIX": "https://login.example.edu/login?url="}
    suffix = detect_library_link("https://www-sciencedirect-com.ezproxy.example.edu/science/article/pii/X")
    assert suffix["updates"] == {"EZPROXY_SUFFIX": "ezproxy.example.edu"}


@pytest.mark.parametrize("url", ["http://proxy.example.edu/login?url=x", "https://user:pass@proxy.example.edu/login?url=x", "https://publisher.example/article", "https://proxy.example.edu/login?token=secret&url=https://publisher.example"])
def test_rejects_unsafe_or_unrecognized_links(url):
    with pytest.raises(ValueError):
        detect_library_link(url)
