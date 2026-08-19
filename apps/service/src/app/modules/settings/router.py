"""HTTP surface for operator-administered settings.

The whole point of this router is that it is the *only* way settings change
at runtime, and that a secret can go in but never come out. `GET` returns
presence and a four-character hint; there is no endpoint, and no response
model in this package, that returns a secret value.

`build_settings_router` takes the store as an injected callable set, matching
every other router here: the durable implementation is a platform secret
store, and this package must not depend on one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException

from .models import (
    ConnectionCheck,
    SecretKey,
    ServiceSettings,
    SettingsUpdateRequest,
)

ReadSettings = Callable[[], Awaitable[ServiceSettings]]
ApplySettings = Callable[[SettingsUpdateRequest], Awaitable[ServiceSettings]]
CheckConnection = Callable[[SecretKey], Awaitable[ConnectionCheck]]


def build_settings_router(
    read_settings: ReadSettings,
    apply_settings: ApplySettings,
    check_connection: CheckConnection,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])

    @router.get("", response_model=ServiceSettings, status_code=200)
    async def get_settings() -> ServiceSettings:
        """Current settings. Secrets appear as presence and a hint, never as values."""

        return await read_settings()

    @router.put("", response_model=ServiceSettings, status_code=200)
    async def put_settings(payload: SettingsUpdateRequest) -> ServiceSettings:
        """Apply a settings change and return the new state.

        Returning the full settings rather than 204 lets the admin screen
        re-render from the service's view instead of its own optimistic one —
        which matters most for secrets, where the client cannot know the
        resulting hint without being told.
        """

        return await apply_settings(payload)

    @router.post(
        "/{key}/test", response_model=ConnectionCheck, status_code=200
    )
    async def test_connection(key: SecretKey) -> ConnectionCheck:
        """Check that a configured credential actually works.

        A 200 with `reachable: false` rather than an error status: the request
        itself succeeded, and the operator needs the reason rendered in the
        form next to the field, not an exception.
        """

        try:
            return await check_connection(key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
