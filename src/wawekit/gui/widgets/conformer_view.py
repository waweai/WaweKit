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
from collections.abc import Sequence
from importlib import resources

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

#: Background colours matching the two themes (3Dmol wants a CSS colour).
_DARK_BG = "#1a1b1e"
_LIGHT_BG = "#ffffff"

#: Colours for radial shells, innermost first (cycled if there are more shells).
_SHELL_COLORS = ("#d2a679", "#2e8b57", "#4682b4", "#a0522d")

#: Opacity of the innermost shell, and how much each shell outward loses.
#: Outer shells must be fainter or they simply hide everything inside them.
_SHELL_OPACITY = 0.30
_SHELL_OPACITY_STEP = 0.07
_SHELL_OPACITY_MIN = 0.08


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
  function wawekitShells(center, shells) {{
    // Draw the radial shells a ShapeDescriptors panel was measured over, as
    // translucent spheres about the same centre the service used. Purely an
    // overlay: it adds no model, so wawekitLoad's zoom and styling still apply.
    viewer.removeAllShapes();
    shells.forEach(function (shell) {{
      viewer.addSphere({{
        center: {{ x: center[0], y: center[1], z: center[2] }},
        radius: shell[0],
        color: shell[1],
        opacity: shell[2],
      }});
    }});
    viewer.render();
  }}
  function wawekitClearShells() {{ viewer.removeAllShapes(); viewer.render(); }}
  function wawekitClear() {{
    viewer.removeAllModels();
    viewer.removeAllShapes();
    viewer.render();
  }}
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
        self._pending_shells: tuple[tuple[float, ...], list[list]] | None = None

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

    def show_shells(self, center: tuple[float, float, float], radii: Sequence[float]) -> None:
        """Overlay the radial shells a 3D descriptor panel was measured over.

        Draws one translucent sphere per radius about ``center``, which must be
        in the same coordinate frame as the displayed conformer — pass
        :attr:`~wawekit.models.shape3d.ShapeDescriptors.center` and
        :attr:`~wawekit.models.shape3d.RadialOptions.shells` together and it
        lines up by construction. Outer shells are drawn fainter so they do not
        obscure the geometry inside them.

        Parameters
        ----------
        center:
            ``(x, y, z)`` the shells are centred on.
        radii:
            Shell radii in ångström.

        """
        shells = []
        for index, radius in enumerate(sorted(radii)):
            opacity = max(_SHELL_OPACITY - index * _SHELL_OPACITY_STEP, _SHELL_OPACITY_MIN)
            shells.append([float(radius), _SHELL_COLORS[index % len(_SHELL_COLORS)], opacity])

        self._pending_shells = (tuple(center), shells)
        if self._loaded:
            self._run(f"wawekitShells({json.dumps(list(center))}, {json.dumps(shells)})")

    def clear_shells(self) -> None:
        """Remove the shell overlay, leaving the molecule displayed."""
        self._pending_shells = None
        if self._loaded:
            self._run("wawekitClearShells()")

    def clear(self) -> None:
        """Remove any displayed molecule and shell overlay."""
        self._pending = None
        self._pending_shells = None
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
        if self._pending_shells is not None:
            center, shells = self._pending_shells
            self._run(f"wawekitShells({json.dumps(list(center))}, {json.dumps(shells)})")

    def _run(self, script: str) -> None:
        """Run a snippet of JavaScript in the page."""
        self._web.page().runJavaScript(script)
