"""Operator voice enrolment and speaker verification (PRD FR-1.5, FR-1.6).

Deliberately exposes no `routers`. `module_loader` mounts already-constructed
routers from packages that need no injection, and this one needs three things
injected — the persistence reads and writes, and the embedder — so it is built
by `build_voiceprint_router(...)` at the composition root like every other
router whose behaviour depends on where it is running.
"""
