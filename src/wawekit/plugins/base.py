"""The plugin contract.

A plugin is any object exposing this shape — Python's structural typing means a
plugin author does not need to import Wawekit to implement it, only to match it,
so :class:`WawekitPlugin` is a :class:`~typing.Protocol`, not a base class to
subclass. That keeps a plugin package's only Wawekit dependency being this one
tiny contract, not the whole application.

Plugins are discovered via **Python entry points** (the same mechanism pip
packages use to register CLI commands), under the group name
:data:`PLUGIN_ENTRY_POINT_GROUP`. A third-party package declares in its
``pyproject.toml``::

    [project.entry-points."wawekit.plugins"]
    my_plugin = "my_package.plugin:MyPlugin"

No plugin registry file inside Wawekit itself needs editing — installing the
package is enough for it to be discovered at the next launch.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

#: The entry-point group Wawekit scans for plugins (see module docstring).
PLUGIN_ENTRY_POINT_GROUP = "wawekit.plugins"


@runtime_checkable
class WawekitPlugin(Protocol):
    """The shape a plugin must have.

    Attributes
    ----------
    name:
        Short, human-readable plugin name shown in the About/Plugins list.
    version:
        Plugin version string (any format; Wawekit does not parse it).

    """

    name: str
    version: str

    def activate(self, context: PluginContext) -> None:
        """Run once at startup after the main window is built.

        Receives a :class:`PluginContext` — the *only* thing a plugin is handed;
        it cannot reach into the window, the models, or other plugins directly.
        That boundary is what lets one broken or malicious plugin be isolated
        instead of having free rein over the application.
        """
        ...


class PluginContext:
    """The narrow, safe surface a plugin is allowed to extend the app through.

    Deliberately minimal: a plugin can add a menu action and a dock panel, and
    nothing else. Widening this surface is a conscious API decision for a later
    version, not something a plugin can route around.

    Parameters
    ----------
    add_menu_action:
        Callback the host provides: ``(label, callback) -> None``, adds an item
        to the Plugins menu.
    add_dock:
        Callback the host provides: ``(title, widget) -> None``, adds a new dock
        panel to the main window.

    """

    def __init__(self, add_menu_action, add_dock) -> None:  # noqa: ANN001 — host callables
        self._add_menu_action = add_menu_action
        self._add_dock = add_dock

    def add_menu_action(self, label: str, callback) -> None:  # noqa: ANN001 — Callable[[], None]
        """Add an item to the Plugins menu that calls ``callback`` when clicked."""
        self._add_menu_action(label, callback)

    def add_dock(self, title: str, widget) -> None:  # noqa: ANN001 — QWidget, no Qt import here
        """Add ``widget`` as a new dockable panel titled ``title``."""
        self._add_dock(title, widget)
