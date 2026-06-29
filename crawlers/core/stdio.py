"""Console stream helpers for standalone spider scripts.

搬自 RideClawAPI app/clients/spiders/stdio.py，零改动（无 app.* 依赖）。
"""
import sys


def ensure_utf8_stdio() -> None:
    """Prefer UTF-8 console output without replacing pytest or host streams."""
    if sys.platform != "win32":
        return

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
