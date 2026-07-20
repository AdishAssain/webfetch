import ipaddress

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from webfetch._safeurl import UnsafeURLError, guard

_nonpublic_ipv4 = (
    st.integers(min_value=0, max_value=2**32 - 1)
    .map(ipaddress.IPv4Address)
    .filter(
        lambda ip: (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    )
)


@settings(max_examples=200)
@given(_nonpublic_ipv4)
def test_every_nonpublic_ipv4_is_blocked(ip):
    with pytest.raises(UnsafeURLError):
        guard(f"http://{ip}/path")


@given(
    st.sampled_from(
        ["file", "ftp", "gopher", "data", "javascript", "ws", "about", "jar", "dict", "mailto"]
    )
)
def test_every_non_web_scheme_is_blocked(scheme):
    with pytest.raises(UnsafeURLError):
        guard(f"{scheme}://example.com/x")
