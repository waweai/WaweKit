"""Icon loading: packaged SVG files → multi-size :class:`QIcon` objects.

Icons ship as hand-authored SVGs inside ``wawekit/resources/icons`` and are
loaded with :mod:`importlib.resources`, so they work identically from source
and from a frozen PyInstaller bundle. Each icon is rasterized at several sizes
(menus, toolbars, window icon) and cached — QIcon then picks the best size.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from importlib import resources

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

#: Raster sizes registered per icon; Qt picks the closest for each use.
_SIZES = (16, 24, 32, 48, 64)


@lru_cache(maxsize=64)
def get_icon(name: str) -> QIcon:
    """Return the icon named ``name`` (an SVG in ``resources/icons``).

    A missing or broken asset logs a warning and returns an empty icon —
    branding must never crash the application.
    """
    try:
        svg = resources.files("wawekit.resources").joinpath(f"icons/{name}.svg").read_bytes()
    except (OSError, ModuleNotFoundError):
        logger.warning("Icon asset %r not found", name)
        return QIcon()

    icon = QIcon()
    renderer = QSvgRenderer(QByteArray(svg))
    for size in _SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(QPixmap.fromImage(image))
    return icon


@lru_cache(maxsize=8)
def get_brand_pixmap(name: str, width: int = 0) -> QPixmap:
    """Return a PNG brand asset (logo/badge) from ``resources/icons``.

    Used for the splash screen and the manual header, where a raster logo is
    wanted rather than a rasterized SVG glyph. A missing asset logs a warning
    and returns a null pixmap — branding must never crash the application.

    Parameters
    ----------
    name:
        Base name of the PNG (e.g. ``wawekit_logo``).
    width:
        If non-zero, the pixmap is smoothly scaled to this width.

    """
    try:
        data = resources.files("wawekit.resources").joinpath(f"icons/{name}.png").read_bytes()
    except (OSError, ModuleNotFoundError):
        logger.warning("Brand asset %r not found", name)
        return QPixmap()
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(data))
    if width and not pixmap.isNull():
        pixmap = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return pixmap


def get_app_icon() -> QIcon:
    """Return the application window icon (the WaweKit badge).

    Falls back to the legacy ``app.svg`` glyph if the badge PNG is missing.
    """
    pixmap = get_brand_pixmap("wawekit_badge")
    return QIcon(pixmap) if not pixmap.isNull() else get_icon("app")
