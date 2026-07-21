"""Wawekit — a professional open-source desktop cheminformatics toolkit.

This package is organized in strict layers (see ``core``, ``models``,
``services``, ``gui``). Dependencies only ever point *downward*: the GUI may
import services and models; the science layers never import the GUI. Keeping
that discipline is what makes the toolkit testable and maintainable.

Public attributes
-----------------
__version__ : str
    Single source of truth for the application version. Read by the GUI
    (About dialog, window title) and by the packaging tooling.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
