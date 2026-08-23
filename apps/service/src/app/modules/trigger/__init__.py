"""The live trigger gate: which finalised utterances deserve a question.

Deliberately exposes no router from here. `module_loader` mounts routers found
on a package's `__init__`, and this package's HTTP surface is built by a
factory the composition root calls with its dependencies, like every other
router in this service.
"""
