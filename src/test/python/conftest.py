from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def design_references_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTWIN_DESIGN_REFERENCES", "")


@pytest.fixture(autouse=True)
def design_system_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTWIN_DESIGN_SYSTEM", "")
