"""Reads a linked SharePoint, OneDrive or Teams document through Microsoft Graph
(PRD FR-3.2).

This is the connector `fetch_body` was written to have and never had. Attaching
a link stored the URL and a tag; the body came back from
`backend.reference_document_bodies`, which nothing in production ever wrote to,
so every linked document contributed an empty string. The compiler then had a
filename and no text, and `POST /bank/compile` returned a job id and an empty
bank — a defect that presents as a missing model.

Three deliberate shapes:

* **The transport is injected.** Building the request — the share-id encoding
  in particular, which Graph is exact about — is the part worth testing, and it
  is testable without a tenant.
* **Credentials are read per call**, like every other vendor credential here,
  so a key entered in Settings takes effect without a restart.
* **Failures name what an operator can act on.** A rejected client secret, a
  document the app registration cannot see and a missing file need three
  different responses, and all three used to be an empty string.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import ReferenceDocumentFetchError

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
LOGIN_ROOT = "https://login.microsoftonline.com"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

#: Refresh this many seconds before the token actually expires, so a fetch
#: that starts just inside the window does not finish just outside it.
_EXPIRY_MARGIN_SECONDS = 60.0


@dataclass(frozen=True)
class GraphCredentials:
    """An Entra ID app registration with application permissions on the tenant.

    Client credentials rather than a pasted access token: a token expires in
    about an hour, and a connector that stops working over lunch is one nobody
    trusts. `Files.Read.All` (and `Sites.Read.All` for team sites) is what the
    registration needs.
    """

    tenant_id: str
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}


class HttpTransport(Protocol):
    """One HTTP round trip. Narrow on purpose: it is a seam, not a client."""

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> Awaitable[HttpResponse]: ...


@dataclass(frozen=True)
class FetchedDocument:
    """What the link actually pointed at: its name on the drive, and its bytes."""

    name: str
    content: bytes


class MicrosoftGraphConnector:
    """Resolves a sharing link to the document behind it."""

    def __init__(
        self,
        credentials: Callable[[], GraphCredentials | None],
        transport: HttpTransport,
        now: Callable[[], float] = time.monotonic,
    ):
        self._credentials = credentials
        self._transport = transport
        self._now = now
        self._token: str | None = None
        self._token_expires_at = 0.0

    @staticmethod
    def share_id(url: str) -> str:
        """Graph's encoding for "the thing this sharing URL points at".

        `u!` then unpadded base64url of the URL. The padding matters: Graph
        rejects the `=` characters standard base64 would leave on the end.
        """

        encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
        return "u!" + encoded.rstrip("=")

    async def fetch(self, url: str) -> FetchedDocument:
        """The document behind `url`, or a `ReferenceDocumentFetchError` saying why not."""

        token = await self._access_token()
        share = self.share_id(url)
        headers = {"Authorization": f"Bearer {token}"}

        metadata = await self._send(
            "GET", f"{GRAPH_ROOT}/shares/{share}/driveItem", headers=headers
        )
        if metadata.status >= 400:
            raise ReferenceDocumentFetchError(
                f"{url}: {_graph_message(metadata)}"
            )
        name = str(metadata.json().get("name") or "").strip()

        content = await self._send(
            "GET", f"{GRAPH_ROOT}/shares/{share}/driveItem/content", headers=headers
        )
        if content.status in (301, 302, 303, 307, 308):
            location = content.headers.get("Location") or content.headers.get("location")
            if not location:
                raise ReferenceDocumentFetchError(
                    f"{url}: the download redirect carried no location"
                )
            # Deliberately no Authorization header: the redirect points at
            # pre-signed storage, and forwarding a Microsoft bearer token to
            # whatever host the header names would hand out a credential.
            content = await self._send("GET", location)

        if content.status >= 400:
            raise ReferenceDocumentFetchError(f"{url}: {_graph_message(content)}")

        return FetchedDocument(name=name, content=content.body)

    async def _access_token(self) -> str:
        credentials = self._credentials()
        if credentials is None:
            raise ReferenceDocumentFetchError(
                "the Microsoft 365 connector is not configured: set the tenant, "
                "client id and client secret in Settings before attaching a link"
            )

        if self._token is not None and self._now() < self._token_expires_at:
            return self._token

        response = await self._send(
            "POST",
            f"{LOGIN_ROOT}/{credentials.tenant_id}/oauth2/v2.0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scope": GRAPH_SCOPE,
            },
        )
        if response.status >= 400:
            raise ReferenceDocumentFetchError(
                f"Microsoft 365 refused the connector's credentials: "
                f"{_login_message(response)}"
            )

        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise ReferenceDocumentFetchError(
                "Microsoft 365 returned no access token for the connector"
            )
        lifetime = float(payload.get("expires_in") or 0.0)
        self._token = token
        self._token_expires_at = self._now() + max(
            lifetime - _EXPIRY_MARGIN_SECONDS, 0.0
        )
        return token

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        try:
            return await self._transport(method, url, headers=headers, data=data)
        except ReferenceDocumentFetchError:
            raise
        except Exception as cause:  # noqa: BLE001 — every transport failure is this one
            raise ReferenceDocumentFetchError(
                f"could not reach Microsoft 365: {cause}"
            ) from cause


def _graph_message(response: HttpResponse) -> str:
    error = response.json().get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if message:
            return str(message)
    return f"Microsoft 365 answered {response.status}"


def _login_message(response: HttpResponse) -> str:
    payload = response.json()
    for key in ("error_description", "error"):
        value = payload.get(key)
        if value:
            return str(value).splitlines()[0]
    return f"sign-in answered {response.status}"


def credentials_from(
    tenant_id: str | None, client_id: str | None, client_secret: str | None
) -> GraphCredentials | None:
    """The three parts, or nothing.

    Half a configuration is worse than none: a tenant and a client id with no
    secret produces `AADSTS...invalid_client`, which reads to an operator like
    a wrong password rather than an unfinished form. Returning `None` routes
    them to the message that names what is missing.
    """

    parts = [(tenant_id or "").strip(), (client_id or "").strip(), (client_secret or "").strip()]
    if not all(parts):
        return None
    tenant, client, secret = parts
    return GraphCredentials(tenant_id=tenant, client_id=client, client_secret=secret)


async def httpx_transport(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
) -> HttpResponse:
    """The real transport, over the HTTP client the service already ships.

    Redirects are *not* followed here. Graph answers a content request with a
    302 to pre-signed storage, and an automatic redirect would forward the
    `Authorization` header to whatever host the `Location` names. The connector
    follows it deliberately, without the token.
    """

    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        response = await client.request(
            method, url, headers=dict(headers or {}), data=dict(data or {}) or None
        )
    return HttpResponse(
        status=response.status_code,
        body=response.content,
        headers={key.title(): value for key, value in response.headers.items()},
    )
