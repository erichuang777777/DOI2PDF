from __future__ import annotations

from importlib.util import find_spec


def module_available(name: str) -> bool:
    """Detect an optional integration without importing or installing it."""
    try:
        return find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def browser_capabilities() -> dict[str, bool]:
    return {
        "playwright": module_available("playwright"),
        "browser_use": module_available("browser_use"),
    }
