from __future__ import annotations

from orchestwin.cli.browser.discovery import BROWSER_NAMES, BrowserProgram, find_browsers
from orchestwin.cli.browser.page import (
    BrowserError,
    Element,
    Page,
    PageSnapshot,
    open_page,
    snapshot_from_document,
)
from orchestwin.cli.browser.targets import matches_text, normalized, resolve_target

__all__ = [
    "BROWSER_NAMES",
    "BrowserError",
    "BrowserProgram",
    "Element",
    "Page",
    "PageSnapshot",
    "find_browsers",
    "matches_text",
    "normalized",
    "open_page",
    "resolve_target",
    "snapshot_from_document",
]
