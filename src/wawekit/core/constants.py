"""Application-wide constant facts.

These values are imported anywhere the app needs to identify itself: the window
title, the About dialog, the config/log directory names, and the packaging
metadata. Centralizing them here means a rename is a one-line change.

Nothing in this module performs logic or I/O — it is pure data.
"""

from __future__ import annotations

from wawekit import __version__

#: Human-facing product name (window titles, dialogs, docs).
APP_NAME: str = "Wawekit"

#: Machine-safe identifier used for the importable package and CLI.
APP_SLUG: str = "wawekit"

#: Organization/author name. Used by Qt's QSettings and OS path helpers to
#: namespace the app's config and data directories.
ORG_NAME: str = "TheWaweAI"

#: Short one-line description shown in the About dialog and packaging metadata.
APP_DESCRIPTION: str = "Desktop workbench for cheminformatics research"

#: Application version, sourced from the package to avoid duplication.
APP_VERSION: str = __version__

#: Organization website.
ORG_URL: str = "https://thewaweai.com"

#: Project homepage / source repository.
PROJECT_URL: str = "https://github.com/waweai/WaweKit"

#: Developer / author details.  Each entry is a dict with name, email(s).
DEVELOPERS: list[dict[str, str | list[str]]] = [
    {
        "name": "Upputoori Sree Vasthav",
        "emails": [
            "sreevasthav.upputoori@gmail.com",
            "sreevasthav-u@thewaweai.com",
        ],
    },
    {
        "name": "S Madhav Varma",
        "emails": [
            "srimadhavvarma@gmail.com",
            "madhav-v@thewaweai.com",
        ],
    },
]

#: SPDX identifier of the project license.
LICENSE: str = "MIT"
