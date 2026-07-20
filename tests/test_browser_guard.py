import pytest

from webfetch._browser import _blocked


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:9000/x",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_blocks_local_metadata_and_bad_schemes(url):
    assert _blocked(url) is True


@pytest.mark.parametrize("url", ["https://example.com/page", "http://data.gov.in/report"])
def test_allows_public_http(url):
    assert _blocked(url) is False
