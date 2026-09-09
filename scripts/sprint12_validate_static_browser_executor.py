"""Opt-in validation of the generic static-source browser executor; no image builds."""

from orchestwin.web_execution.static_browser_validation import main

if __name__ == "__main__":
    raise SystemExit(main())
