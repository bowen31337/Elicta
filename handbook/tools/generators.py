"""The registry of generated chapters: source reader wired to renderer.

Adding a generated chapter means adding an entry here and a `[[chapter]]`
block in `book.toml`. Nothing else knows the list, so the two files are the
only places a new generated chapter has to be declared.

Not every generator here is used. The handbook is a guide for the people who
*use* Elicta, so the generators that describe its internals are not mounted
in `book.toml`. They are kept, working and tested, for a companion document
aimed at the people who build it — and they are named in `UNMOUNTED` below
rather than left to be discovered as a surprise. A test asserts that every
generator is either mounted or listed there, so "built and quietly wired to
nothing" cannot happen by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import render
import sources


#: Generators that exist and are deliberately not in the guide, with the
#: reason. Anything here is a decision; anything neither here nor in
#: `book.toml` is an oversight, and a test says so.
UNMOUNTED = {
    "crates": "describes the internal components; not useful to a reader using the product",
    "routes": "describes the service's network interface; internal detail",
    "service_modules": "describes the code layout; internal detail",
    "desktop_features": "describes source folders rather than what a user sees",
    "env": "describes settings supplied by file; the guide covers the Settings screen instead",
    "commands": "describes commands for people working on the code",
}


@dataclass(frozen=True)
class Generator:
    #: Repo-relative paths this chapter is derived from. Shown on the page
    #: and watched for drift, so the two can never disagree.
    paths: list[str]
    collect: Callable
    body: Callable


GENERATORS: dict[str, Generator] = {
    "readiness": Generator(
        paths=[sources.JOURNEYS],
        collect=sources.collect_readiness,
        body=render.readiness_body,
    ),
    "crates": Generator(
        paths=["core/crates", "core/shared", sources.REGISTRY],
        collect=sources.collect_crates,
        body=render.crate_body,
    ),
    "routes": Generator(
        paths=[sources.OPENAPI],
        collect=sources.collect_routes,
        body=render.route_body,
    ),
    "env": Generator(
        paths=[sources.ENV_EXAMPLE],
        collect=sources.collect_env_vars,
        body=render.env_body,
    ),
    "service_modules": Generator(
        paths=[sources.SERVICE_MODULES],
        collect=sources.collect_service_modules,
        body=lambda data: render.component_body(
            data,
            "Each folder is one feature of the service. A feature has to be "
            "connected in one of two places before the running service can reach "
            "it; a feature connected in neither is shipped unreachable, and the "
            "chapter on adding something new explains where those two places are.",
        ),
    ),
    "desktop_features": Generator(
        paths=[sources.DESKTOP_FEATURES],
        collect=sources.collect_desktop_features,
        body=lambda data: render.component_body(
            data, "One folder per screen or panel the operator can see."
        ),
    ),
    "commands": Generator(
        paths=[sources.COMMANDS],
        collect=sources.collect_commands,
        body=render.command_body,
    ),
}
