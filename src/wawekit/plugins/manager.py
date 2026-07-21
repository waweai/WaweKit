"""Plugin discovery and loading.

Qt-free by design (like every service in this project) — discovery uses only
:mod:`importlib.metadata`, so it is independently testable and could in
principle run in a CLI that lists installed plugins without starting the GUI.

Resilience is the central design constraint: a third-party plugin is
**untrusted code**. One plugin that raises during import or activation must
never take the whole application down with it — exactly the same
"one bad molecule must not abort the run" discipline used throughout the
chemistry services, applied here to code instead of data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points

from wawekit.plugins.base import PLUGIN_ENTRY_POINT_GROUP, PluginContext, WawekitPlugin

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginLoadResult:
    """Outcome of loading one plugin."""

    entry_point_name: str
    plugin: WawekitPlugin | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the plugin loaded and activated successfully."""
        return self.error is None and self.plugin is not None


@dataclass(slots=True)
class PluginLoadReport:
    """Outcome of a full discovery-and-activation pass.

    Attributes
    ----------
    results:
        One :class:`PluginLoadResult` per discovered entry point.

    """

    results: list[PluginLoadResult] = field(default_factory=list)

    @property
    def loaded(self) -> list[WawekitPlugin]:
        """Successfully activated plugins."""
        return [r.plugin for r in self.results if r.ok and r.plugin is not None]

    @property
    def failures(self) -> list[PluginLoadResult]:
        """Entry points that failed to import, construct, or activate."""
        return [r for r in self.results if not r.ok]


def discover_plugins() -> list[tuple[str, type]]:
    """Return ``(entry_point_name, plugin_class)`` for every registered plugin.

    Only *resolves* the entry points (imports the module and gets the class);
    it does not instantiate or activate anything, so discovery alone cannot be
    broken by a plugin's constructor or ``activate()``.
    """
    found: list[tuple[str, type]] = []
    for ep in entry_points(group=PLUGIN_ENTRY_POINT_GROUP):
        try:
            found.append((ep.name, ep.load()))
        except Exception:  # noqa: BLE001 — one bad entry point must not stop discovery
            logger.exception("Failed to resolve plugin entry point %r", ep.name)
    return found


def load_plugins(context: PluginContext) -> PluginLoadReport:
    """Discover, instantiate and activate every registered plugin.

    Parameters
    ----------
    context:
        The narrow extension surface (see :class:`~wawekit.plugins.base.PluginContext`)
        handed to every plugin's ``activate()``.

    Returns
    -------
    PluginLoadReport
        Which plugins loaded, and why any did not.

    """
    report = PluginLoadReport()
    for name, plugin_class in discover_plugins():
        try:
            plugin = plugin_class()
            if not isinstance(plugin, WawekitPlugin):
                raise TypeError(
                    f"{plugin_class!r} does not implement the WawekitPlugin protocol "
                    "(missing name/version/activate)"
                )
            plugin.activate(context)
        except Exception as exc:  # noqa: BLE001 — isolate one plugin's failure
            logger.exception("Plugin %r failed to load", name)
            result = PluginLoadResult(entry_point_name=name, plugin=None, error=str(exc))
            report.results.append(result)
        else:
            logger.info("Loaded plugin %r (%s v%s)", name, plugin.name, plugin.version)
            report.results.append(PluginLoadResult(entry_point_name=name, plugin=plugin))
    return report
