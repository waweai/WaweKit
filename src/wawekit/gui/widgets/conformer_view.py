"""Interactive 3D conformer viewer, powered by a vendored 3Dmol.js.

Qt has no native 3D molecule widget, so we render one the way most of the field
does — with `3Dmol.js <https://3dmol.csb.pitt.edu/>`_ (WebGL) inside a
:class:`~PySide6.QtWebEngineWidgets.QWebEngineView`. The library is vendored
under ``wawekit/resources/web`` and inlined into the page, so the viewer works
**fully offline** with no CDN.

How it drives the page
----------------------
The heavy 3Dmol.js is loaded exactly once, when the widget is built. Thereafter
each conformer is shown by calling a tiny JavaScript function
(``wawekitLoad``) with the conformer's MDL mol block — reloading the whole page
per click would re-parse half a megabyte of script every time. Because the page
loads asynchronously, a mol block requested before ``loadFinished`` fires is held
in ``_pending`` and applied once the page is ready.
"""

from __future__ import annotations

import json
import logging
from importlib import resources

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

#: Background colours matching the two themes (3Dmol wants a CSS colour).
_DARK_BG = "#1a1b1e"
_LIGHT_BG = "#ffffff"


def _load_3dmol_js() -> str:
    """Read the vendored 3Dmol.js source (empty string if somehow missing)."""
    try:
        return (
            resources.files("wawekit.resources")
            .joinpath("web/3Dmol-min.js")
            .read_text(encoding="utf-8")
        )
    except (OSError, ModuleNotFoundError):
        logger.error("Vendored 3Dmol-min.js not found; the 3D viewer will be blank")
        return ""


def _build_page(dark: bool) -> str:
    """Build the one-time HTML page: inlined 3Dmol.js + a small drawing API."""
    background = _DARK_BG if dark else _LIGHT_BG
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; }}
  #viewer {{ width: 100%; height: 100%; position: relative; }}
</style>
<script>{_load_3dmol_js()}</script>
</head>
<body>
<div id="viewer"></div>
<script>
  let viewer = $3Dmol.createViewer("viewer", {{ backgroundColor: "{background}" }});
  function wawekitLoad(molblock) {{
    viewer.removeAllModels();
    viewer.addModel(molblock, "mol");
    viewer.setStyle({{}}, {{ stick: {{ radius: 0.13 }}, sphere: {{ scale: 0.22 }} }});
    viewer.zoomTo();
    viewer.render();
  }}
  function wawekitBackground(color) {{
    viewer.setBackgroundColor(color);
    viewer.render();
  }}
  function wawekitClear() {{ viewer.removeAllModels(); viewer.render(); }}
</script>
</body>
</html>"""


class ConformerView(QWidget):
    """A 3Dmol.js viewer that shows one conformer's geometry at a time.

    Parameters
    ----------
    dark:
        Initial background palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = dark
        self._loaded = False
        self._pending: str | None = None

        self._web = QWebEngineView(self)
        self._web.loadFinished.connect(self._on_load_finished)
        self._web.setHtml(_build_page(dark))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._web)

    # ------------------------------------------------------------- public API
    def show_molblock(self, molblock: str) -> None:
        """Display the 3D geometry in ``molblock`` (an MDL mol block).

        Held until the page finishes loading if it is not ready yet.
        """
        if self._loaded:
            self._run(f"wawekitLoad({json.dumps(molblock)})")
        else:
            self._pending = molblock

    def clear(self) -> None:
        """Remove any displayed molecule."""
        self._pending = None
        if self._loaded:
            self._run("wawekitClear()")

    def set_dark(self, dark: bool) -> None:
        """Switch the viewer background to match the application theme."""
        if dark != self._dark:
            self._dark = dark
            color = _DARK_BG if dark else _LIGHT_BG
            if self._loaded:
                self._run(f"wawekitBackground({json.dumps(color)})")

    # --------------------------------------------------------------- internals
    def _on_load_finished(self, ok: bool) -> None:
        """Mark the page ready and flush any conformer requested during load."""
        self._loaded = ok
        if not ok:
            logger.error("3D viewer page failed to load")
            return
        if self._pending is not None:
            self._run(f"wawekitLoad({json.dumps(self._pending)})")
            self._pending = None

    def _run(self, script: str) -> None:
        """Run a snippet of JavaScript in the page."""
        self._web.page().runJavaScript(script)
