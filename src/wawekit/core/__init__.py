"""Core infrastructure shared by every other layer.

``core`` is the foundation of the dependency graph: nothing above it (models,
services, gui) is imported here, and everything above it may import from here.
It provides configuration, logging, filesystem paths, and constants.
"""
