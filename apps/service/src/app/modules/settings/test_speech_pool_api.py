"""Managing the pool over the API the screen uses.

Without this the pool is a shape nobody can fill: the settings screen had no
field for the keys that matter, which is the whole reason it exists.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.composition import Backend, build_app
from app.modules.settings.store import InMemorySettingsStore


def _client() -> tuple[TestClient, InMemorySettingsStore]:
    store = InMemorySettingsStore(read_environment=False)
    return TestClient(build_app(Backend(), settings_store=store)), store


class TestAddingACredential:
    def test_it_appears_in_the_pool_and_its_value_never_comes_back(self):
        client, _ = _client()

        created = client.post(
            "/api/admin/settings/speech/credentials",
            json={"vendor": "deepgram", "label": "Northwind", "value": "dg-secret"},
        )

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["vendor"] == "deepgram"
        assert body["label"] == "Northwind"
        # Write-only, like every other secret here.
        assert "dg-secret" not in created.text
        assert body["hint"] == "cret"

    def test_it_makes_the_live_lane_ready(self):
        client, _ = _client()
        before = client.get("/api/admin/settings").json()
        assert not _live(before)["ready"]

        client.post(
            "/api/admin/settings/speech/credentials",
            json={"vendor": "deepgram", "label": "Northwind", "value": "dg-secret"},
        )

        assert _live(client.get("/api/admin/settings").json())["ready"]

    def test_a_second_key_for_the_same_vendor_is_kept_rather_than_overwriting(self):
        """The failure this whole pool replaced.

        One field meant the second key silently replaced the first — its hint
        changed and nothing said so.
        """

        client, _ = _client()
        for label in ("first", "second"):
            client.post(
                "/api/admin/settings/speech/credentials",
                json={"vendor": "deepgram", "label": label, "value": f"dg-{label}"},
            )

        pool = client.get("/api/admin/settings").json()["speech"]

        assert [c["label"] for c in pool["credentials"]] == ["first", "second"]


class TestChangingAndRemoving:
    def test_a_credential_can_be_disabled_without_losing_its_secret(self):
        client, _ = _client()
        made = client.post(
            "/api/admin/settings/speech/credentials",
            json={"vendor": "deepgram", "label": "spare", "value": "dg-secret"},
        ).json()

        patched = client.patch(
            f"/api/admin/settings/speech/credentials/{made['id']}",
            json={"enabled": False},
        )

        assert patched.status_code == 200, patched.text
        assert patched.json()["enabled"] is False
        # Still configured: disabling takes it out of service, not out of the store.
        assert patched.json()["hint"] == "cret"

    def test_removing_one_takes_its_secret_with_it(self):
        client, store = _client()
        made = client.post(
            "/api/admin/settings/speech/credentials",
            json={"vendor": "deepgram", "label": "gone", "value": "dg-secret"},
        ).json()

        removed = client.delete(f"/api/admin/settings/speech/credentials/{made['id']}")

        assert removed.status_code == 204, removed.text
        assert client.get("/api/admin/settings").json()["speech"]["credentials"] == []
        # No orphaned secret left behind for an id nothing references.
        from app.modules.settings.speech_credentials import secret_key_for

        assert store.get_secret(secret_key_for(made["id"])) is None

    def test_removing_one_nobody_has_is_a_404(self):
        client, _ = _client()

        assert client.delete("/api/admin/settings/speech/credentials/nope").status_code == 404

    def test_the_policy_can_be_changed(self):
        client, _ = _client()

        response = client.put(
            "/api/admin/settings/speech/policy", json={"policy": "rotate"}
        )

        assert response.status_code == 200, response.text
        assert client.get("/api/admin/settings").json()["speech"]["policy"] == "rotate"


def _live(body: dict) -> dict:
    return next(e for e in body["readiness"] if e["capability"] == "live_nudges")


class TestTestingOne:
    """Per credential, which is what makes the answer unambiguous.

    The single field this replaced could be tested against the wrong vendor:
    renaming it from the dropdown above changed what it claimed to be while
    the service still probed what it had saved, and the operator was told
    "Deepgram rejected the credential (401)" under a field labelled
    "AssemblyAI key". A pooled credential carries its own vendor, so there is
    no gap left to test across.
    """

    def test_the_verdict_comes_back_as_a_200_not_an_error(self):
        client, _ = _client()
        made = client.post(
            "/api/admin/settings/speech/credentials",
            json={"vendor": "custom", "label": "in-house", "value": "x-secret"},
        ).json()

        response = client.post(
            f"/api/admin/settings/speech/credentials/{made['id']}/test"
        )

        # A failed check is not a failed request: the operator needs the
        # reason rendered beside the key, not an exception page.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["reachable"] is False
        # A custom service has no probe by definition, so this must not claim
        # a reachability it never tested.
        assert "not verified" in body["detail"]
        assert "cret" in body["detail"]

    def test_testing_one_nobody_has_is_a_404(self):
        client, _ = _client()

        assert (
            client.post("/api/admin/settings/speech/credentials/nope/test").status_code
            == 404
        )
