"""A settings file written by an older build must still open.

`ConnectorSettings` forbids extra keys on purpose — a typo'd setting should
fail loudly rather than be silently ignored. That same strictness means
*removing* a field breaks every settings file that still contains it, and the
failure is at startup, on the operator's own saved configuration.

`live_vendor` was removed when the speech credential pool took over choosing
the provider. This is the one-way door it left behind, handled by name.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.settings.models import ConnectorSettings, without_retired_connector_keys


class TestOpeningAFileThatPredatesThePool:
    def test_a_retired_key_is_dropped_rather_than_refused(self):
        stored = { "keyterm_prompting": True}

        settings = ConnectorSettings(**without_retired_connector_keys(stored))

        assert settings.keyterm_prompting is True

    def test_a_key_nobody_retired_still_fails(self):
        """The strictness is the point and must survive the migration.

        A blanket `extra="ignore"` would fix this file and silently swallow
        the next typo, which is the failure the setting exists to prevent.
        """

        stored = {"keytrem_prompting": True}

        with pytest.raises(ValidationError):
            ConnectorSettings(**without_retired_connector_keys(stored))

    def test_it_leaves_a_clean_payload_alone(self):
        stored = {"keyterm_prompting": False}

        assert without_retired_connector_keys(stored) == stored
