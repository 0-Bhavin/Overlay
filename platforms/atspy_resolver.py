"""AT-SPI accessibility resolver for Linux.

Uses the ``pyatspi`` library to traverse the running accessibility tree and
return screen coordinates for named UI elements.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

try:
    import pyatspi  # type: ignore[import]
except ModuleNotFoundError as _err:
    raise ModuleNotFoundError(
        "pyatspi is not installed. Run: pip install pyatspi"
    ) from _err

# pyatspi uses its own Accessible type; keep the import for type hints only
# when running a type-checker so we don't break at runtime on non-Linux.
if TYPE_CHECKING:
    from pyatspi import Accessible  # type: ignore[import]


class ATSpiResolver:
    """Resolves UI element coordinates via the AT-SPI accessibility API.

    All public methods return ``None`` on any failure and never raise.
    """

    # ------------------------------------------------------------------
    # Window search
    # ------------------------------------------------------------------

    def find_window(self, app_name: str) -> "Accessible | None":
        """Find the first running application whose name contains *app_name*.

        The comparison is case-insensitive and partial (substring) match.

        Parameters
        ----------
        app_name:
            Name fragment to search for, e.g. ``"gedit"`` or ``"Word"``.

        Returns
        -------
        Accessible | None
            The application-level ``Accessible`` node, or ``None`` if not
            found or on any AT-SPI error.
        """
        needle = app_name.lower()
        try:
            desktop = pyatspi.Registry.getDesktop(0)
            for app in desktop:
                try:
                    if app is not None and needle in (app.name or "").lower():
                        return app
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------
    # Element search
    # ------------------------------------------------------------------

    def find_element(
        self, app_name: str, target_name: str
    ) -> "Accessible | None":
        """Search the accessibility tree for an element matching *target_name*.

        Uses BFS so the most shallow (most prominent) match is returned first.
        The comparison is case-insensitive and partial (substring) match
        against both the element's ``name`` and ``description`` attributes.

        Parameters
        ----------
        app_name:
            Passed to :meth:`find_window` to locate the root application node.
        target_name:
            Name fragment to look for, e.g. ``"Insert tab"`` or ``"text area"``.

        Returns
        -------
        Accessible | None
            The matching element, or ``None`` if not found.
        """
        app = self.find_window(app_name)
        if app is None:
            return None

        needle = target_name.lower()
        queue: deque[Accessible] = deque([app])

        while queue:
            node = queue.popleft()
            try:
                name = (node.name or "").lower()
                desc = (node.description or "").lower()
                if needle in name or needle in desc:
                    return node
                for i in range(node.childCount):
                    child = node.getChildAtIndex(i)
                    if child is not None:
                        queue.append(child)
            except Exception:  # noqa: BLE001
                # Individual nodes may raise; skip and continue BFS
                continue

        return None

    # ------------------------------------------------------------------
    # Coordinate extraction
    # ------------------------------------------------------------------

    def get_coords(
        self, element: "Accessible"
    ) -> tuple[int, int, int, int] | None:
        """Return screen coordinates ``(x, y, width, height)`` for *element*.

        Uses ``element.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)``
        which returns coordinates relative to the desktop (screen) origin.

        Parameters
        ----------
        element:
            An ``Accessible`` node previously returned by :meth:`find_element`.

        Returns
        -------
        tuple[int, int, int, int] | None
            ``(x, y, width, height)`` in screen pixels, or ``None`` on failure.
        """
        try:
            component = element.queryComponent()
            extents = component.getExtents(pyatspi.DESKTOP_COORDS)
            # extents is an Atspi.Rect with fields x, y, width, height
            return (extents.x, extents.y, extents.width, extents.height)
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Standalone smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    resolver = ATSpiResolver()
    APP = "gedit"

    print(f"Searching for application: {APP!r} …")
    app_node = resolver.find_window(APP)
    if app_node is None:
        print(f"  ✗ Application {APP!r} not found. Is it running?")
        sys.exit(1)
    print(f"  ✓ Found: {app_node.name!r}")

    print("Searching for first text area …")
    element = resolver.find_element(APP, "text")
    if element is None:
        print("  ✗ No text area element found.")
        sys.exit(1)
    print(f"  ✓ Found element: name={element.name!r}  role={element.getRoleName()!r}")

    coords = resolver.get_coords(element)
    if coords is None:
        print("  ✗ Could not retrieve coordinates.")
        sys.exit(1)
    x, y, w, h = coords
    print(f"  ✓ Coords: x={x}  y={y}  width={w}  height={h}")
