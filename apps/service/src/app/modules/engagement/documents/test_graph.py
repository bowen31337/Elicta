"""The Microsoft Graph connector that reads a linked document (PRD FR-3.2).

Attaching a document by link recorded its URL and its tag and stopped there:
`fetch_body` returned `""` from a dictionary nothing ever wrote to. So a
SharePoint document contributed a filename to the compiler and nothing else,
and the question bank came back empty for a reason that looked like a missing
model.

The transport is injected, so these drive the real request-building — the
share-id encoding, the token reuse, the failure messages — without a tenant.
"""

from __future__ import annotations

import base64
import json

import pytest

from .errors import ReferenceDocumentFetchError
from .graph import (
    GraphCredentials,
    HttpResponse,
    MicrosoftGraphConnector,
    httpx_transport,
)

SHARE_URL = "https://acme.sharepoint.com/sites/proj/Shared%20Documents/Scoping.docx"
CREDENTIALS = GraphCredentials(
    tenant_id="tenant-1", client_id="client-1", client_secret="shhh"
)
LOGIN = "https://login.microsoftonline.com/"
GRAPH = "https://graph.microsoft.com/"


def json_body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


class FakeGraph:
    """Answers the three requests a fetch makes, and records every one."""

    def __init__(
        self,
        *,
        token: HttpResponse | None = None,
        metadata: HttpResponse | None = None,
        content: HttpResponse | None = None,
        signed: HttpResponse | None = None,
    ):
        self.token = token or HttpResponse(
            status=200, body=json_body({"access_token": "tok-1", "expires_in": 3600})
        )
        self.metadata = metadata or HttpResponse(
            status=200, body=json_body({"name": "Scoping.docx"})
        )
        self.content = content or HttpResponse(status=200, body=b"the scoping deck")
        self.signed = signed or HttpResponse(status=200, body=b"redirected body")
        self.calls: list[tuple[str, str, dict, dict]] = []

    async def __call__(self, method, url, *, headers=None, data=None):
        self.calls.append((method, url, dict(headers or {}), dict(data or {})))
        if url.startswith(LOGIN):
            return self.token
        if url.startswith(GRAPH) and url.endswith("/content"):
            return self.content
        if url.startswith(GRAPH):
            return self.metadata
        return self.signed

    @property
    def urls(self) -> list[str]:
        return [url for _m, url, _h, _d in self.calls]

    def logins(self) -> list[str]:
        return [url for url in self.urls if url.startswith(LOGIN)]


def connector(transport, *, credentials=CREDENTIALS, clock=None):
    ticks = iter(clock if clock is not None else [0.0] * 40)
    return MicrosoftGraphConnector(
        credentials=lambda: credentials,
        transport=transport,
        now=lambda: next(ticks),
    )


class TestTheShareIdentifier:
    def test_the_url_is_encoded_the_way_graph_specifies(self):
        expected = "u!" + base64.urlsafe_b64encode(
            SHARE_URL.encode("utf-8")
        ).decode("ascii").rstrip("=")

        assert MicrosoftGraphConnector.share_id(SHARE_URL) == expected

    def test_the_padding_is_stripped_because_graph_rejects_it(self):
        assert "=" not in MicrosoftGraphConnector.share_id(SHARE_URL)

    @pytest.mark.asyncio
    async def test_the_identifier_is_what_the_request_is_addressed_to(self):
        transport = FakeGraph()

        await connector(transport).fetch(SHARE_URL)

        share = MicrosoftGraphConnector.share_id(SHARE_URL)
        assert any(f"/shares/{share}/driveItem" in url for url in transport.urls)


class TestFetching:
    @pytest.mark.asyncio
    async def test_returns_the_document_name_and_its_bytes(self):
        transport = FakeGraph(content=HttpResponse(status=200, body=b"scoping body"))

        fetched = await connector(transport).fetch(SHARE_URL)

        assert fetched.name == "Scoping.docx"
        assert fetched.content == b"scoping body"

    @pytest.mark.asyncio
    async def test_the_graph_requests_carry_the_bearer_token(self):
        transport = FakeGraph()

        await connector(transport).fetch(SHARE_URL)

        graph_headers = [
            headers for _m, url, headers, _d in transport.calls if url.startswith(GRAPH)
        ]
        assert graph_headers
        assert all(h.get("Authorization") == "Bearer tok-1" for h in graph_headers)

    @pytest.mark.asyncio
    async def test_a_content_redirect_is_followed_without_the_bearer_token(self):
        # Graph answers /content with a 302 to a pre-signed storage URL. Sending
        # the bearer token on to that host would hand a Microsoft credential to
        # whatever the Location header names.
        transport = FakeGraph(
            content=HttpResponse(
                status=302,
                body=b"",
                headers={"Location": "https://storage.example/blob?sig=1"},
            )
        )

        fetched = await connector(transport).fetch(SHARE_URL)

        assert fetched.content == b"redirected body"
        signed = [h for _m, url, h, _d in transport.calls if url.startswith("https://storage")]
        assert signed
        assert "Authorization" not in signed[0]


class TestTheToken:
    @pytest.mark.asyncio
    async def test_one_token_serves_more_than_one_document(self):
        transport = FakeGraph()
        connection = connector(transport)

        await connection.fetch(SHARE_URL)
        await connection.fetch(SHARE_URL)

        assert len(transport.logins()) == 1

    @pytest.mark.asyncio
    async def test_an_expired_token_is_replaced(self):
        transport = FakeGraph(
            token=HttpResponse(
                status=200,
                body=json_body({"access_token": "tok-1", "expires_in": 60}),
            )
        )
        # The clock jumps past the token's lifetime between the two fetches.
        connection = connector(transport, clock=[0.0, 0.0, 0.0] + [10_000.0] * 20)

        await connection.fetch(SHARE_URL)
        await connection.fetch(SHARE_URL)

        assert len(transport.logins()) == 2

    @pytest.mark.asyncio
    async def test_the_client_secret_goes_to_microsoft_and_nowhere_else(self):
        transport = FakeGraph()

        await connector(transport).fetch(SHARE_URL)

        for _method, url, headers, data in transport.calls:
            if url.startswith(LOGIN):
                assert data.get("client_secret") == "shhh"
            else:
                assert "shhh" not in json.dumps({**headers, **data})


class TestFailuresAnOperatorCanActOn:
    @pytest.mark.asyncio
    async def test_no_credentials_configured_says_what_to_configure(self):
        transport = FakeGraph()

        with pytest.raises(ReferenceDocumentFetchError) as raised:
            await connector(transport, credentials=None).fetch(SHARE_URL)

        assert "not configured" in str(raised.value).lower()
        assert transport.calls == []

    @pytest.mark.asyncio
    async def test_a_rejected_credential_is_not_reported_as_a_missing_file(self):
        transport = FakeGraph(
            token=HttpResponse(
                status=401,
                body=json_body({"error_description": "AADSTS7000215: bad secret"}),
            )
        )

        with pytest.raises(ReferenceDocumentFetchError) as raised:
            await connector(transport).fetch(SHARE_URL)

        assert "AADSTS7000215" in str(raised.value)

    @pytest.mark.asyncio
    async def test_a_document_the_app_cannot_see_says_so(self):
        transport = FakeGraph(
            metadata=HttpResponse(
                status=403,
                body=json_body({"error": {"message": "Access denied"}}),
            )
        )

        with pytest.raises(ReferenceDocumentFetchError) as raised:
            await connector(transport).fetch(SHARE_URL)

        assert "Access denied" in str(raised.value)

    @pytest.mark.asyncio
    async def test_a_missing_document_says_which_link(self):
        transport = FakeGraph(
            metadata=HttpResponse(
                status=404, body=json_body({"error": {"message": "Item not found"}})
            )
        )

        with pytest.raises(ReferenceDocumentFetchError) as raised:
            await connector(transport).fetch(SHARE_URL)

        assert "Item not found" in str(raised.value)

    @pytest.mark.asyncio
    async def test_a_transport_that_cannot_connect_is_a_fetch_error_not_a_crash(self):
        async def unreachable(method, url, *, headers=None, data=None):
            raise OSError("Name or service not known")

        with pytest.raises(ReferenceDocumentFetchError) as raised:
            await connector(unreachable).fetch(SHARE_URL)

        assert "not known" in str(raised.value)


class TestCredentialsFromSettings:
    """Half a configuration is not a configuration.

    A tenant and a client id with no secret produces a sign-in rejection that
    reads like a wrong password, when the real answer is that nobody finished
    filling the form in. All three or nothing, so the message the operator gets
    is the one they can act on.
    """

    def test_all_three_present_gives_credentials(self):
        from .graph import credentials_from

        assert credentials_from("t", "c", "s") == GraphCredentials(
            tenant_id="t", client_id="c", client_secret="s"
        )

    @pytest.mark.parametrize(
        ("tenant", "client", "secret"),
        [
            (None, "c", "s"),
            ("t", None, "s"),
            ("t", "c", None),
            ("", "c", "s"),
            ("t", "c", "   "),
        ],
    )
    def test_anything_missing_gives_nothing(self, tenant, client, secret):
        from .graph import credentials_from

        assert credentials_from(tenant, client, secret) is None

    def test_surrounding_whitespace_is_not_part_of_a_tenant_id(self):
        from .graph import credentials_from

        assert credentials_from(" t ", " c ", " s ") == GraphCredentials(
            tenant_id="t", client_id="c", client_secret="s"
        )


# --- what a malformed answer is allowed to do ------------------------------


def test_a_body_that_is_not_json_reads_as_an_empty_payload():
    # Graph answers an error with HTML from a proxy often enough that parsing
    # it must not raise: the status is still the useful signal.
    assert HttpResponse(status=502, body=b"<html>gateway</html>").json() == {}


def test_a_body_that_is_not_utf8_reads_as_an_empty_payload():
    assert HttpResponse(status=200, body=b"\xff\xfe\x00").json() == {}


async def test_an_error_with_no_message_still_names_the_status():
    # The operator gets something actionable even when Graph explains nothing.
    graph = FakeGraph(metadata=HttpResponse(status=503, body=b"<html>busy</html>"))

    with pytest.raises(ReferenceDocumentFetchError, match="Microsoft 365 answered 503"):
        await connector(graph).fetch(SHARE_URL)


async def test_a_sign_in_refusal_with_no_description_still_names_the_status():
    graph = FakeGraph(token=HttpResponse(status=500, body=b"not json"))

    with pytest.raises(ReferenceDocumentFetchError, match="sign-in answered 500"):
        await connector(graph).fetch(SHARE_URL)


async def test_a_sign_in_that_returns_no_token_is_refused():
    # A 200 with no token would otherwise become an Authorization header
    # reading "Bearer ", and the failure would surface two requests later.
    graph = FakeGraph(token=HttpResponse(status=200, body=json_body({"expires_in": 3600})))

    with pytest.raises(ReferenceDocumentFetchError, match="returned no access token"):
        await connector(graph).fetch(SHARE_URL)


# --- the download redirect --------------------------------------------------


async def test_a_download_redirect_with_no_location_is_refused():
    graph = FakeGraph(content=HttpResponse(status=302, body=b"", headers={}))

    with pytest.raises(ReferenceDocumentFetchError, match="redirect carried no location"):
        await connector(graph).fetch(SHARE_URL)


async def test_a_failed_download_is_refused_rather_than_attached_empty():
    # Attaching a document with an empty body is what made the bank come back
    # empty and read as a missing model.
    graph = FakeGraph(
        content=HttpResponse(
            status=404, body=json_body({"error": {"message": "Item not found"}})
        )
    )

    with pytest.raises(ReferenceDocumentFetchError, match="Item not found"):
        await connector(graph).fetch(SHARE_URL)


async def test_a_transport_that_already_explained_itself_is_not_rewrapped():
    # Otherwise the operator reads "could not reach Microsoft 365: <the real
    # reason>" and the real reason is buried one level down.
    async def transport(method, url, *, headers=None, data=None):
        raise ReferenceDocumentFetchError("the connector is not configured")

    with pytest.raises(ReferenceDocumentFetchError) as caught:
        await connector(transport).fetch(SHARE_URL)

    assert str(caught.value) == "the connector is not configured"


# --- the real transport -----------------------------------------------------


async def test_the_real_transport_does_not_follow_the_download_redirect(monkeypatch):
    """The redirect points at pre-signed storage on a host Microsoft chose.

    Following it automatically would forward the bearer token to that host,
    which is why the connector follows it itself, without the header.
    """

    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            302, headers={"location": "https://storage.example/blob"}, content=b""
        )

    original = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    response = await httpx_transport(
        "GET",
        "https://graph.microsoft.com/v1.0/shares/u!abc/driveItem/content",
        headers={"Authorization": "Bearer tok-1"},
    )

    assert response.status == 302
    assert response.headers["Location"] == "https://storage.example/blob"
    assert len(seen) == 1, "the redirect was followed inside the client"


async def test_the_real_transport_sends_form_data_when_it_has_any(monkeypatch):
    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})

    original = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    response = await httpx_transport(
        "POST",
        "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "client_id": "client-1"},
    )

    assert response.status == 200
    assert json.loads(response.body)["access_token"] == "tok-1"
    assert b"grant_type=client_credentials" in seen[0].content
