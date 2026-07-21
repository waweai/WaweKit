"""Reusable background-worker infrastructure.

Long operations (parsing a 50k-molecule SDF, computing descriptors, generating
conformers) must never run on the GUI thread, or the window freezes. Qt's
answer is a thread pool:

* :class:`~PySide6.QtCore.QRunnable` — a unit of work executed by
  :class:`~PySide6.QtCore.QThreadPool` (threads are reused, never hand-managed).
* **Signals** — the only safe way to send results back to the GUI thread.
  Qt automatically queues cross-thread signal deliveries onto the receiver's
  event loop, so slots in widgets run on the GUI thread without locks.

Because :class:`QRunnable` is not a :class:`QObject` (it cannot own signals),
the standard pattern is a small companion :class:`WorkerSignals` object — this
is the idiom used across professional Qt codebases.

This module uses **QtCore only** (see the ``services`` layering rule).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals a background worker can emit toward the GUI thread.

    Attributes
    ----------
    progress:
        ``(done, total)`` counts, forwarded from the wrapped function.
    finished:
        Emitted with the function's return value on success.
    error:
        Emitted with a human-readable message if the function raised.

    """

    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)


class FunctionWorker(QRunnable):
    """Run any callable on the thread pool and report through signals.

    Parameters
    ----------
    fn:
        The callable to execute on a pooled thread.
    *args, **kwargs:
        Forwarded to ``fn``.
    inject_progress:
        If ``True``, the worker passes ``progress=self.signals.progress.emit``
        as a keyword argument, so functions with an optional ``progress``
        callback (like the molecule loader) report into Qt signals without
        knowing Qt exists.

    Notes
    -----
    ``setAutoDelete(False)`` keeps ownership on the Python side: the caller
    holds a reference until the worker completes, then drops it. This avoids
    the classic "Internal C++ object already deleted" pitfall.

    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        inject_progress: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._inject_progress = inject_progress
        self.setAutoDelete(False)

    def run(self) -> None:  # noqa: D102 — QRunnable interface
        try:
            kwargs = dict(self._kwargs)
            if self._inject_progress:
                kwargs["progress"] = self.signals.progress.emit
            result = self._fn(*self._args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — boundary: report, don't crash the thread
            logger.exception("Background task %r failed", getattr(self._fn, "__name__", self._fn))
            self.signals.error.emit(str(exc))
        else:
            self.signals.finished.emit(result)
