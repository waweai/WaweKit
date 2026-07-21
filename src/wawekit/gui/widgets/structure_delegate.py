"""Structure thumbnails inside table cells.

Qt's Model/View architecture separates data from painting; a **delegate**
(:class:`~PySide6.QtWidgets.QStyledItemDelegate`) is the object that actually
paints each cell. By installing a custom delegate on the *Structure* column we
draw 2D depictions directly inside the molecule table — the signature look of
professional chemistry software.

Performance design
------------------
Qt only paints **visible** cells, so scrolling a 100k-row table renders only
the thumbnails on screen. Each rendered thumbnail is cached in a dict keyed by
canonical SMILES (+ theme), so re-paints (selection changes, scrolling back)
cost a dict lookup. Pixmaps are rendered at 2× resolution with a device pixel
ratio so they stay crisp on HiDPI screens.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.rendering.mol_renderer import render_svg

logger = logging.getLogger(__name__)

#: Custom item-data role through which the model exposes the MoleculeRecord.
RECORD_ROLE = int(Qt.ItemDataRole.UserRole) + 1

#: Logical thumbnail size (cell size follows, plus padding).
THUMB_WIDTH = 120
THUMB_HEIGHT = 78
_PADDING = 4

#: Oversampling factor for crisp HiDPI rendering.
_SCALE = 2

#: Drop the whole cache beyond this many entries (simple, effective bound).
_CACHE_LIMIT = 4096


class StructureDelegate(QStyledItemDelegate):
    """Paints a cached 2D depiction for the cell's :class:`MoleculeRecord`.

    Parameters
    ----------
    parent:
        Standard Qt parent (usually the view).
    dark:
        Whether to render with the dark-mode atom palette; switchable at
        runtime via :meth:`set_dark`.

    """

    def __init__(self, parent: QWidget | None = None, dark: bool = True) -> None:
        super().__init__(parent)
        self._dark = dark
        # Keyed by (canonical SMILES, highlighted-atoms tuple-or-None): the same
        # molecule caches separately with and without a substructure highlight.
        self._cache: dict[tuple[str, tuple[int, ...] | None], QPixmap] = {}

    def set_dark(self, dark: bool) -> None:
        """Switch palette and invalidate every cached thumbnail."""
        if dark != self._dark:
            self._dark = dark
            self._cache.clear()

    # ------------------------------------------------------------ Qt overrides
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Draw the selection background, then the centered structure pixmap."""
        record = index.data(RECORD_ROLE)
        if not isinstance(record, MoleculeRecord):
            super().paint(painter, option, index)
            return

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        pixmap = self._pixmap_for(record)
        if pixmap is not None:
            # Center using the LOGICAL size: pixmap.rect() is in physical
            # pixels (2x oversampled), but painting happens in logical
            # coordinates — mixing them shifts the image into adjacent cells.
            size = pixmap.deviceIndependentSize()
            target = QRectF(0.0, 0.0, size.width(), size.height())
            target.moveCenter(option.rect.toRectF().center())
            painter.save()
            painter.setClipRect(option.rect)  # never bleed into neighbors
            painter.drawPixmap(target.topLeft(), pixmap)
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """Reserve room for the thumbnail plus padding."""
        return QSize(THUMB_WIDTH + 2 * _PADDING, THUMB_HEIGHT + 2 * _PADDING)

    # ---------------------------------------------------------------- helpers
    def _pixmap_for(self, record: MoleculeRecord) -> QPixmap | None:
        """Return the cached thumbnail for ``record``, rendering it on miss."""
        # Fold the substructure highlight into the cache key: when a new search
        # changes which atoms are lit, the key changes and the thumbnail
        # re-renders; clear the query and it reverts to the plain cached image.
        hit = record.substructure_match
        highlight = tuple(sorted(hit.atoms)) if hit is not None and hit.is_match else None
        key = (record.smiles, highlight)
        pixmap = self._cache.get(key)
        if pixmap is not None:
            return pixmap

        try:
            svg = render_svg(
                record.mol, THUMB_WIDTH, THUMB_HEIGHT, dark=self._dark, highlight_atoms=highlight
            )
        except Exception:  # noqa: BLE001 — a bad depiction must never crash painting
            logger.exception("Failed to render thumbnail for %s", record.name)
            return None

        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        image = QImage(THUMB_WIDTH * _SCALE, THUMB_HEIGHT * _SCALE, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        svg_painter = QPainter(image)
        renderer.render(svg_painter)
        svg_painter.end()

        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(_SCALE)

        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()  # simple bound; avoids unbounded growth
        self._cache[key] = pixmap
        return pixmap
