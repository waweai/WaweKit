"""Tests for the in-app user manual and brand assets."""

from __future__ import annotations

import re
from importlib import resources

from wawekit.gui.dialogs.manual_dialog import ManualDialog, _load_manual
from wawekit.gui.icons import get_app_icon, get_brand_pixmap


def test_manual_html_loads():
    html, image_dir, icons_dir = _load_manual()
    assert "<h1" in html
    assert image_dir  # points at the packaged manual directory
    assert icons_dir  # points at the packaged icons directory (brand assets)


def test_every_referenced_image_ships_in_the_package():
    # A manual with broken images is false documentation: every <img src="...">
    # must resolve to a packaged file — checked against both search paths the
    # dialog actually uses (manual/ for screenshots, icons/ for brand assets),
    # and after the same logo.png -> wawekit_logo.png swap the dialog applies.
    html, _, _ = _load_manual()
    manual_dir = resources.files("wawekit.resources").joinpath("manual")
    icons_dir = resources.files("wawekit.resources").joinpath("icons")
    html = html.replace('src="logo.png"', 'src="wawekit_logo.png"')
    referenced = re.findall(r'<img src="([^"]+)"', html)
    assert referenced  # the manual is illustrated
    for name in referenced:
        assert (
            manual_dir.joinpath(name).is_file() or icons_dir.joinpath(name).is_file()
        ), f"manual references missing image {name!r}"


def test_manual_covers_every_menu_feature():
    # The manual's promise is "users won't miss details" — every major feature
    # must at least have a section.
    html, _, _ = _load_manual()
    for feature in (
        "Standardize",
        "Descriptors",
        "Fingerprints",
        "Similarity",
        "Scaffold",
        "Conformers",
        "Chemical space",
        "Clustering",
        "Substructure",
        "Batch",
        "Reports",
        "Settings",
        "Reproducibility",
        "Plugins",
    ):
        assert feature.lower() in html.lower(), f"manual has no section for {feature}"


def test_manual_dialog_constructs(qtbot):
    dialog = ManualDialog()
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "WaweKit User Manual"


def test_brand_pixmap_and_app_icon_load(qapp):
    assert not get_brand_pixmap("wawekit_logo").isNull()
    assert not get_brand_pixmap("wawekit_badge").isNull()
    assert not get_app_icon().isNull()


def test_brand_pixmap_missing_asset_returns_null(qapp):
    assert get_brand_pixmap("no_such_asset").isNull()
