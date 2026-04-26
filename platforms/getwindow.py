"""Platform resolver router.

All application code should import from this module::

    from platforms.getwindow import get_resolver

    resolver = get_resolver()
    coords   = resolver.resolve("Microsoft Word", "Insert tab")

:class:`~platforms.hybrid_resolver.HybridResolver` wraps
:class:`~platforms.uia_resolver.UIAResolver` and returns ``(L, T, R, B)``
screen-pixel coordinates from Windows UI Automation.
"""
from __future__ import annotations

import os


def get_resolver():
    """Return a :class:`~platforms.hybrid_resolver.HybridResolver` instance.

    The API key is read from the ``GEMINI_API_KEY`` environment variable.
    """
    from platforms.hybrid_resolver import HybridResolver  # local import avoids circular deps
    api_key = os.environ.get("GEMINI_API_KEY", "AIzaSyCEGOdUJvfs37fUz6QwOKskOJDJbizmnJ8")
    return HybridResolver(api_key=api_key)
