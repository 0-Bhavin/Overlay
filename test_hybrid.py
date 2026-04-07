"""Quick smoke-test for HybridResolver.

Open Notepad first, then run:
    python test_hybrid.py

Tests UIA and Gemini Vision separately, prints timings and coords.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(__file__))

from platforms.hybrid_resolver import HybridResolver

APP    = "Notepad"
TARGET = "File"


def _separator(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print('─' * 50)


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("⚠  GEMINI_API_KEY not set — Vision fallback will fail.")

    resolver = HybridResolver(api_key=api_key)

    # ── 1. UIA only ───────────────────────────────────────────────────
    _separator("1 · UIA only")
    if resolver._uia is not None:
        t0 = time.perf_counter()
        try:
            element = resolver._uia.find_element(APP, TARGET)
            coords  = resolver._uia.get_coords(element) if element else None
        except Exception as exc:
            coords = None
            print(f"   ERROR: {exc}")
        elapsed = time.perf_counter() - t0
        if coords:
            print(f"   ✓ UIA found: {coords}  ({elapsed*1000:.1f} ms)")
        else:
            print(f"   ✗ UIA did not find '{TARGET}'  ({elapsed*1000:.1f} ms)")
    else:
        print("   (UIAResolver unavailable on this platform)")

    # ── 2. Vision only ────────────────────────────────────────────────
    _separator("2 · Gemini Vision only")
    t0 = time.perf_counter()
    coords = resolver._vision_resolve(APP, TARGET)
    elapsed = time.perf_counter() - t0
    if coords:
        print(f"   ✓ Vision found: {coords}  ({elapsed*1000:.1f} ms)")
    else:
        print(f"   ✗ Vision did not find '{TARGET}'  ({elapsed*1000:.1f} ms)")

    # ── 3. Full hybrid (UIA → Vision fallback) ────────────────────────
    _separator("3 · Full hybrid  resolve()")
    t0 = time.perf_counter()
    coords = resolver.resolve(APP, TARGET)
    elapsed = time.perf_counter() - t0
    if coords:
        x, y, w, h = coords
        print(f"   ✓ Result: x={x}  y={y}  w={w}  h={h}  ({elapsed*1000:.1f} ms)")
    else:
        print(f"   ✗ not found  ({elapsed*1000:.1f} ms)")

    print()


if __name__ == "__main__":
    main()
