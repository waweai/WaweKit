"""A minimal reference Wawekit plugin.

Demonstrates the whole contract in a few lines: a class with ``name``,
``version``, and an ``activate(context)`` method that adds one menu item. Install
this package (``pip install -e examples/example-plugin``) and it is discovered
automatically the next time Wawekit starts — no change to Wawekit itself.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


class ExamplePlugin:
    """Adds a single "Say Hello" item to the Plugins menu."""

    name = "Example Plugin"
    version = "0.1.0"

    def activate(self, context) -> None:  # noqa: ANN001 — PluginContext, untyped to avoid the dep
        """Register the menu action. Called once at Wawekit startup."""
        context.add_menu_action("Say Hello", self._say_hello)

    @staticmethod
    def _say_hello() -> None:
        """Show a message box — proof the plugin's code actually ran."""
        QMessageBox.information(None, "Example Plugin", "Hello from a Wawekit plugin!")
