import httpcore
import pytest

import httpx
from httpx._utils import URLPattern


def url_to_origin(url: str):
    """
    Given a URL string, return the origin in the raw tuple format that
    `httpcore` uses for it's representation.
    """
    scheme, host, port = httpx.URL(url).raw[:3]
    return httpcore.URL(scheme=scheme, host=host, port=port, target="/")


@pytest.mark.parametrize(
    ["proxies", "expected_proxies"],
    [
        ("http://127.0.0.1", [("all://", "http://127.0.0.1")]),
        ({"all://": "http://127.0.0.1"}, [("all://", "http://127.0.0.1")]),
        (
            {"http://": "http://127.0.0.1", "https://": "https://127.0.0.1"},
            [("http://", "http://127.0.0.1"), ("https://", "https://127.0.0.1")],
        ),
        (httpx.Proxy("http://127.0.0.1"), [("all://", "http://127.0.0.1")]),
        (
            {
                "https://": httpx.Proxy("https://127.0.0.1"),
                "all://": "http://127.0.0.1",
            },
            [("all://", "http://127.0.0.1"), ("https://", "https://127.0.0.1")],
        ),
    ],
)
def test_proxies_parameter(proxies, expected_proxies):
    client = httpx.Client(proxies=proxies)

    for proxy_key, url in expected_proxies:
        pattern = URLPattern(proxy_key)
        assert pattern in client._mounts
        proxy = client._mounts[pattern]
        assert isinstance(proxy, httpx.HTTPTransport)
        assert isinstance(proxy._pool, httpcore.HTTPProxy)
        assert proxy._pool._proxy_url == url_to_origin(url)

    assert len(expected_proxies) == len(client._mounts)


PROXY_URL = "http://[::1]"


@pytest.mark.parametrize(
    ["url", "proxies", "expected"],
    [
        ("http://example.com", None, None),
        ("http://example.com", {}, None),
        ("http://example.com", {"https://": PROXY_URL}, None),
        ("http://example.com", {"http://example.net": PROXY_URL}, None),
        # Using "*" should match any domain name.
        ("http://example.com", {"http://*": PROXY_URL}, PROXY_URL),
        ("https://example.com", {"http://*": PROXY_URL}, None),
        # Using "example.com" should match example.com, but not www.example.com
        ("http://example.com", {"http://example.com": PROXY_URL}, PROXY_URL),
        ("http://www.example.com", {"http://example.com": PROXY_URL}, None),
        # Using "*.example.com" should match www.example.com, but not example.com
        ("http://example.com", {"http://*.example.com": PROXY_URL}, None),
        ("http://www.example.com", {"http://*.example.com": PROXY_URL}, PROXY_URL),
        # Using "*example.com" should match example.com and www.example.com
        ("http://example.com", {"http://*example.com": PROXY_URL}, PROXY_URL),
        ("http://www.example.com", {"http://*example.com": PROXY_URL}, PROXY_URL),
        ("http://wwwexample.com", {"http://*example.com": PROXY_URL}, None),
        # ...
        ("http://example.com:443", {"http://example.com": PROXY_URL}, PROXY_URL),
        ("http://example.com", {"all://": PROXY_URL}, PROXY_URL),
        ("http://example.com", {"all://": PROXY_URL, "http://example.com": None}, None),
        ("http://example.com", {"http://": PROXY_URL}, PROXY_URL),
        ("http://example.com", {"all://example.com": PROXY_URL}, PROXY_URL),
        ("http://example.com", {"http://example.com": PROXY_URL}, PROXY_URL),
        ("http://example.com", {"http://example.com:80": PROXY_URL}, PROXY_URL),
        ("http://example.com:8080", {"http://example.com:8080": PROXY_URL}, PROXY_URL),
        ("http://example.com:8080", {"http://example.com": PROXY_URL}, PROXY_URL),
        (
            "http://example.com",
            {
                "all://": PROXY_URL + ":1",
                "http://": PROXY_URL + ":2",
                "all://example.com": PROXY_URL + ":3",
                "http://example.com": PROXY_URL + ":4",
            },
            PROXY_URL + ":4",
        ),
        (
            "http://example.com",
            {
                "all://": PROXY_URL + ":1",
                "http://": PROXY_URL + ":2",
                "all://example.com": PROXY_URL + ":3",
            },
            PROXY_URL + ":3",
        ),
        (
            "http://example.com",
            {"all://": PROXY_URL + ":1", "http://": PROXY_URL + ":2"},
            PROXY_URL + ":2",
        ),
    ],
)
def test_transport_for_request(url, proxies, expected):
    client = httpx.Client(proxies=proxies)
    transport = client._transport_for_url(httpx.URL(url))

    if expected is None:
        assert transport is client._transport
    else:
        assert isinstance(transport, httpx.HTTPTransport)
        assert isinstance(transport._pool, httpcore.HTTPProxy)
        assert transport._pool._proxy_url == url_to_origin(expected)


@pytest.mark.asyncio
@pytest.mark.network
async def test_async_proxy_close():
    try:
        client = httpx.AsyncClient(proxies={"https://": PROXY_URL})
        await client.get("http://example.com")
    finally:
        await client.aclose()


@pytest.mark.network
def test_sync_proxy_close():
    try:
        client = httpx.Client(proxies={"https://": PROXY_URL})
        client.get("http://example.com")
    finally:
        client.close()


def test_unsupported_proxy_scheme():
    with pytest.raises(ValueError):
        httpx.Client(proxies="ftp://127.0.0.1")


@pytest.mark.parametrize(
    ["url", "env", "expected"],
    [
        ("http://google.com", {}, None),
        (
            "http://google.com",
            {"HTTP_PROXY": "http://example.com"},
            "http://example.com",
        ),
        # Auto prepend http scheme
        ("http://google.com", {"HTTP_PROXY": "example.com"}, "http://example.com"),
        (
            "http://google.com",
            {"HTTP_PROXY": "http://example.com", "NO_PROXY": "google.com"},
            None,
        ),
        # Everything proxied when NO_PROXY is empty/unset
        (
            "http://127.0.0.1",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": ""},
            "http://localhost:123",
        ),
        # Not proxied if NO_PROXY matches URL.
        (
            "http://127.0.0.1",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "127.0.0.1"},
            None,
        ),
        # Proxied if NO_PROXY scheme does not match URL.
        (
            "http://127.0.0.1",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "https://127.0.0.1"},
            "http://localhost:123",
        ),
        # Proxied if NO_PROXY scheme does not match host.
        (
            "http://127.0.0.1",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "1.1.1.1"},
            "http://localhost:123",
        ),
        # Not proxied if NO_PROXY matches host domain suffix.
        (
            "http://courses.mit.edu",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "mit.edu"},
            None,
        ),
        # Proxied even though NO_PROXY matches host domain *prefix*.
        (
            "https://mit.edu.info",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "mit.edu"},
            "http://localhost:123",
        ),
        # Not proxied if one item in NO_PROXY case matches host domain suffix.
        (
            "https://mit.edu.info",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "mit.edu,edu.info"},
            None,
        ),
        # Not proxied if one item in NO_PROXY case matches host domain suffix.
        # May include whitespace.
        (
            "https://mit.edu.info",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "mit.edu, edu.info"},
            None,
        ),
        # Proxied if no items in NO_PROXY match.
        (
            "https://mit.edu.info",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "mit.edu,mit.info"},
            "http://localhost:123",
        ),
        # Proxied if NO_PROXY domain doesn't match.
        (
            "https://foo.example.com",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "www.example.com"},
            "http://localhost:123",
        ),
        # Not proxied for subdomains matching NO_PROXY, with a leading ".".
        (
            "https://www.example1.com",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": ".example1.com"},
            None,
        ),
        # Proxied, because NO_PROXY subdomains only match if "." separated.
        (
            "https://www.example2.com",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "ample2.com"},
            "http://localhost:123",
        ),
        # No requests are proxied if NO_PROXY="*" is set.
        (
            "https://www.example3.com",
            {"ALL_PROXY": "http://localhost:123", "NO_PROXY": "*"},
            None,
        ),
    ],
)
@pytest.mark.parametrize("client_class", [httpx.Client, httpx.AsyncClient])
def test_proxies_environ(monkeypatch, client_class, url, env, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    client = client_class()
    transport = client._transport_for_url(httpx.URL(url))

    if expected is None:
        assert transport == client._transport
    else:
        assert transport._pool._proxy_url == url_to_origin(expected)


@pytest.mark.parametrize(
    ["proxies", "is_valid"],
    [
        ({"http": "http://127.0.0.1"}, False),
        ({"https": "http://127.0.0.1"}, False),
        ({"all": "http://127.0.0.1"}, False),
        ({"http://": "http://127.0.0.1"}, True),
        ({"https://": "http://127.0.0.1"}, True),
        ({"all://": "http://127.0.0.1"}, True),
    ],
)
def test_for_deprecated_proxy_params(proxies, is_valid):
    if not is_valid:
        with pytest.raises(ValueError):
            httpx.Client(proxies=proxies)
    else:
        httpx.Client(proxies=proxies)


def http_proxy_stand_in(supports_http1_http2, type_error=None):
    """
    Create a stand-in for `httpcore.HTTPProxy`, mirroring either the
    signature of httpcore 0.14.4+ (accepting `http1`/`http2`), or the
    signature of earlier httpcore releases (without `http1`/`http2`).

    Optionally raises `TypeError` from within the constructor itself.
    """

    class NewSignatureHTTPProxy:
        attempts = []

        def __init__(
            self,
            proxy_url,
            proxy_headers=None,
            ssl_context=None,
            max_connections=None,
            max_keepalive_connections=None,
            keepalive_expiry=None,
            http1=None,
            http2=None,
        ):
            self.attempts.append(
                {
                    "proxy_url": proxy_url,
                    "proxy_headers": proxy_headers,
                    "http1": http1,
                    "http2": http2,
                }
            )
            if type_error is not None:
                raise TypeError(type_error)

    class OldSignatureHTTPProxy:
        attempts = []

        def __init__(
            self,
            proxy_url,
            proxy_headers=None,
            ssl_context=None,
            max_connections=None,
            max_keepalive_connections=None,
            keepalive_expiry=None,
        ):
            self.attempts.append(
                {"proxy_url": proxy_url, "proxy_headers": proxy_headers}
            )
            if type_error is not None:
                raise TypeError(type_error)

    if supports_http1_http2:
        return NewSignatureHTTPProxy
    return OldSignatureHTTPProxy


@pytest.mark.parametrize(["http1", "http2"], [(True, False), (True, True)])
def test_proxy_transport_forwards_http1_http2(monkeypatch, http1, http2):
    """
    The `http1`/`http2` arguments should be passed through to
    `httpcore.HTTPProxy`, so that tunneled connections can negotiate
    the same protocol versions as direct connections.
    """
    stand_in = http_proxy_stand_in(supports_http1_http2=True)
    monkeypatch.setattr(httpcore, "HTTPProxy", stand_in)

    httpx.HTTPTransport(
        proxy=httpx.Proxy("http://username:password@127.0.0.1:8080"),
        http1=http1,
        http2=http2,
    )

    (attempt,) = stand_in.attempts
    assert attempt["proxy_url"] == url_to_origin("http://127.0.0.1:8080")
    assert attempt["http1"] is http1
    assert attempt["http2"] is http2
    assert (
        b"Proxy-Authorization",
        b"Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
    ) in attempt["proxy_headers"]


@pytest.mark.parametrize(["http1", "http2"], [(True, False), (True, True)])
def test_proxy_transport_http1_http2_fallback(monkeypatch, http1, http2):
    """
    Versions of httpcore prior to 0.14.4 don't accept `http1`/`http2`
    on `HTTPProxy`. Against those, the transport should fall back to
    constructing the proxy pool without them.
    """
    stand_in = http_proxy_stand_in(supports_http1_http2=False)
    monkeypatch.setattr(httpcore, "HTTPProxy", stand_in)

    transport = httpx.HTTPTransport(
        proxy=httpx.Proxy("http://username:password@127.0.0.1:8080"),
        http1=http1,
        http2=http2,
    )

    assert isinstance(transport._pool, stand_in)
    (attempt,) = stand_in.attempts
    assert attempt["proxy_url"] == url_to_origin("http://127.0.0.1:8080")
    assert "http1" not in attempt
    assert "http2" not in attempt
    assert (
        b"Proxy-Authorization",
        b"Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
    ) in attempt["proxy_headers"]


def test_proxy_transport_does_not_suppress_constructor_type_error(monkeypatch):
    """
    A `TypeError` raised from within the `httpcore.HTTPProxy` constructor
    itself should not be mistaken for an outdated httpcore signature,
    and should not trigger the fallback.
    """
    stand_in = http_proxy_stand_in(
        supports_http1_http2=True, type_error="a genuine TypeError"
    )
    monkeypatch.setattr(httpcore, "HTTPProxy", stand_in)

    with pytest.raises(TypeError, match="a genuine TypeError"):
        httpx.HTTPTransport(proxy=httpx.Proxy("http://127.0.0.1:8080"), http2=True)

    # The constructor was only called once, with no fallback retry.
    assert len(stand_in.attempts) == 1


def test_proxy_transport_fallback_does_not_suppress_constructor_type_error(
    monkeypatch,
):
    """
    When the fallback is used against an outdated httpcore signature,
    a `TypeError` raised from within the retried constructor should
    still propagate.
    """
    stand_in = http_proxy_stand_in(
        supports_http1_http2=False, type_error="a genuine TypeError"
    )
    monkeypatch.setattr(httpcore, "HTTPProxy", stand_in)

    with pytest.raises(TypeError, match="a genuine TypeError"):
        httpx.HTTPTransport(proxy=httpx.Proxy("http://127.0.0.1:8080"), http2=True)


def test_client_proxy_transport_http2(monkeypatch):
    """
    A client with `http2=True` should pass the protocol flags through
    to the proxy transport, so that HTTP/2 can be negotiated on
    connections tunneled through the proxy.
    """
    stand_in = http_proxy_stand_in(supports_http1_http2=True)
    monkeypatch.setattr(httpcore, "HTTPProxy", stand_in)

    client = httpx.Client(http2=True, proxies="http://username:password@127.0.0.1:8080")

    assert isinstance(client._mounts[URLPattern("all://")], httpx.HTTPTransport)
    (attempt,) = stand_in.attempts
    assert attempt["http1"] is True
    assert attempt["http2"] is True
    assert (
        b"Proxy-Authorization",
        b"Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
    ) in attempt["proxy_headers"]
