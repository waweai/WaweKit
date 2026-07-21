"""Services — orchestration between the GUI and the models.

This layer hosts file loaders, computation pipelines, and background workers.

Layering rule (refined in Module 2)
-----------------------------------
* ``models`` — pure Python + RDKit. No Qt at all.
* ``services`` — may use **QtCore only** (signals, threads, QRunnable), because
  cross-thread communication needs Qt's signal machinery. Never QtWidgets.
* ``gui`` — the only layer allowed to import QtWidgets.

Services depend on ``models`` and ``core`` but never on ``gui``.
"""
