"""Which service this is, for whoever found it on a port.

Deliberately exposes no `routers`: `module_loader` is for features that need
no injection *and* nothing else to mount them, and this one is mounted in
`composition.build_app` beside every other route. Two mounting paths for one
router would serve it twice.
"""
