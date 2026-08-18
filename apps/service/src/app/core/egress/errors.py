"""Error types raised by the two halves of the egress chokepoint."""


class EgressTransportError(Exception):
    """The outbound call to the external processor failed."""


class EgressLogError(Exception):
    """Persisting the `egress_log` audit row failed.

    Raised rather than swallowed: an egress that can't be audited is the
    exact failure the chokepoint exists to prevent.
    """
