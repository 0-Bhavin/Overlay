"""Hybrid coordinate resolver.

Tries Windows UI Automation first (fast, exact).
Falls back to Gemini Vision (screenshot → Gemini → bounding box) when UIA
cannot locate the element.
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import logging
import time

import google.generativeai as genai  # type: ignore[import]
import mss
import mss.tools
from PIL import Image

_log = logging.getLogger(__name__)


class HybridResolver:
    """Resolve UI element coordinates via UIA → Gemini Vision fallback.

    Parameters
    ----------
    api_key:
        Google Generative AI API key used for Gemini Vision calls.
    """

    _VISION_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(self._VISION_MODEL)

        # Screenshot cache: avoid re-capturing within 500 ms
        self._screenshot_cache: tuple[float, bytes] | None = None  # (timestamp, jpeg_bytes)

        # Try to instantiate UIAResolver; gracefully degrade if unavailable.
        try:
            from platforms.uia_resolver import UIAResolver  # type: ignore[import]
            self._uia = UIAResolver()
            _log.info("HybridResolver: UIAResolver initialised successfully.")
        except Exception as exc:  # noqa: BLE001
            _log.warning("HybridResolver: UIAResolver unavailable (%s) — vision-only mode.", exc)
            self._uia = None

    # ------------------------------------------------------------------
    # Primary public method
    # ------------------------------------------------------------------

    def resolve(
        self,
        app_name: str,
        target_name: str,
    ) -> tuple[int, int, int, int] | None:
        """Return ``(x, y, w, h)`` screen coordinates for *target_name*.

        Tries UIAutomation first; falls back to Gemini Vision on failure.

        Parameters
        ----------
        app_name:
            Application name fragment used to locate the target window with UIA.
        target_name:
            Human-readable name of the UI element to locate.

        Returns
        -------
        tuple[int, int, int, int] | None
            Screen coordinates ``(x, y, width, height)``, or ``None`` if the
            element could not be found by either resolver.
        """
        # ── 1. UIA fast path ──────────────────────────────────────────
        if self._uia is not None:
            try:
                element = self._uia.find_element(app_name, target_name)
                if element is not None:
                    coords = self._uia.get_coords(element)
                    if coords is not None:
                        _log.info(
                            "UIA resolved %r → %s", target_name, coords
                        )
                        return coords
            except Exception as exc:  # noqa: BLE001
                _log.warning("UIA lookup failed for %r: %s", target_name, exc)

        # ── 2. Gemini Vision fallback ─────────────────────────────────
        _log.warning(
            "UIA could not locate %r — falling back to Gemini Vision.", target_name
        )
        return self._vision_resolve(app_name, target_name)

    # ------------------------------------------------------------------
    # UIAResolver-compatible stub interface
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str):  # noqa: ANN201
        """Stub — satisfies the resolver interface; always returns ``None``.

        Use :meth:`resolve` for the full hybrid lookup.
        """
        return None

    def get_coords(self, element) -> None:  # noqa: ANN001
        """Stub — satisfies the resolver interface; always returns ``None``."""
        return None

    # ------------------------------------------------------------------
    # Vision resolution
    # ------------------------------------------------------------------

    def _vision_resolve(
        self,
        app_name: str,
        target_name: str,
    ) -> tuple[int, int, int, int] | None:
        """Capture the primary monitor and ask Gemini Vision to find *target_name*.

        Optimisations applied:
        - Screenshot cached for 500 ms to avoid re-capture on rapid calls.
        - Image resized to max 1280 px wide (thumbnail) before encoding.
        - JPEG quality 60 to minimise payload size.
        - Gemini API call runs in a ThreadPoolExecutor with an 8-second timeout.

        Parameters
        ----------
        app_name:
            Name of the application shown in the screenshot (used in prompt).
        target_name:
            Human-readable name of the UI element to locate.

        Returns
        -------
        tuple[int, int, int, int] | None
            ``(x, y, width, height)`` or ``None`` on failure / not found.
        """
        try:
            # ── 1. Screenshot (cached for 500 ms) ────────────────────
            now = time.monotonic()
            if (
                self._screenshot_cache is not None
                and (now - self._screenshot_cache[0]) < 0.5
            ):
                jpeg_bytes = self._screenshot_cache[1]
                _log.debug("_vision_resolve: using cached screenshot")
            else:
                with mss.mss() as sct:
                    raw = sct.grab(sct.monitors[1])

                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                # ── 2. Resize to max 1280 px wide ─────────────────────
                img.thumbnail((1280, 1280 * img.height // img.width), Image.LANCZOS)

                # ── 3. Encode as JPEG quality 60 ─────────────────────
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=60)
                jpeg_bytes = buf.getvalue()
                self._screenshot_cache = (time.monotonic(), jpeg_bytes)

            kb = len(jpeg_bytes) / 1024
            _log.info("_vision_resolve: sending %.1f KB to Gemini", kb)

            # ── 4. Build prompt ───────────────────────────────────────
            prompt = (
                f'This is a screenshot of {app_name}. '
                f'Find the UI element called \'{target_name}\'. '
                "It may be a button, menu item, tab, or text field.\n"
                'Return ONLY JSON: {"x": <px>, "y": <px>, "w": <px>, "h": <px>}\n'
                'If not found: {"x": null, "y": null, "w": null, "h": null}'
            )

            image_part = {"mime_type": "image/jpeg", "data": jpeg_bytes}

            # ── 5. API call with 8-second timeout ─────────────────────
            def _call_gemini():
                return self._model.generate_content([prompt, image_part])

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call_gemini)
                try:
                    response = future.result(timeout=8)
                except concurrent.futures.TimeoutError:
                    _log.error("_vision_resolve: Gemini API timed out after 8 s")
                    return None

            raw_text = (response.text or "").strip()

            # ── 6. Strip accidental ```json fences ────────────────────
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                raw_text = "\n".join(
                    lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                ).strip()

            # ── 7. Parse JSON ─────────────────────────────────────────
            data = json.loads(raw_text)
            x, y, w, h = data.get("x"), data.get("y"), data.get("w"), data.get("h")

            if x is None or y is None:
                _log.warning(
                    "Gemini Vision could not locate %r in the screenshot.", target_name
                )
                return None

            coords = (int(x), int(y), int(w), int(h))
            _log.info("Gemini Vision resolved %r → %s", target_name, coords)
            return coords

        except Exception as exc:  # noqa: BLE001
            _log.error("Gemini Vision resolution failed for %r: %s", target_name, exc)
            return None
