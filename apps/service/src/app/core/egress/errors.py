"""Error types raised by the two halves of the egress chokepoint."""


class EgressTransportError(Exception):
    """The outbound call to the external processor failed."""


class EgressRegionError(Exception):
    """The request's engagement has no processing region pinned (PRD NFR-2.2).

    Raised before the transport is invoked, rather than falling back to a
    default region: sending on behalf of an unpinned engagement is exactly
    the residency drift NFR-2.2 exists to prevent.
    """


class EgressLogError(Exception):
    """Persisting the `egress_log` audit row failed.

    Raised rather than swallowed: an egress that can't be audited is the
    exact failure the chokepoint exists to prevent.
    """
