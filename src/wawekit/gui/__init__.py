"""The presentation layer (PySide6 / Qt).

This is the *top* of the dependency graph. Widgets here may import from
``services``, ``models`` and ``core`` — but code in those layers must never
import from ``gui``. That one rule keeps the chemistry testable without a
display and lets the UI evolve independently.
"""
