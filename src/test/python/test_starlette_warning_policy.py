"""Keep warning-as-error while isolating one upstream TestClient deprecation."""

from __future__ import annotations

import builtins
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MESSAGE = (
    "The anyio.abc.BlockingPortal alias is deprecated, "
    "use anyio.from_thread.BlockingPortal instead."
)


def _filters() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["pytest"]["ini_options"]["filterwarnings"]


def _apply_filters() -> None:
    warnings.resetwarnings()
    for specification in _filters():
        parts = (specification.split(":") + [""] * 5)[:5]
        action, message, category, module, line = parts
        warnings.filterwarnings(
            action,
            message,
            getattr(builtins, category) if category else Warning,
            module,
            int(line or 0),
        )


def test_default_warning_policy_remains_error() -> None:
    assert _filters()[0] == "error"
    assert not any(
        item in _filters()
        for item in (
            "ignore",
            "ignore::DeprecationWarning",
            "ignore:::starlette.*",
        )
    )


def test_only_the_known_upstream_alias_warning_is_tolerated() -> None:
    with warnings.catch_warnings():
        _apply_filters()
        warnings.warn_explicit(
            MESSAGE,
            DeprecationWarning,
            "starlette/testclient.py",
            53,
            module="starlette.testclient",
        )


@pytest.mark.parametrize(
    ("message", "module", "category"),
    [
        ("A different deprecated API", "starlette.testclient", DeprecationWarning),
        (MESSAGE, "orchestwin.api", DeprecationWarning),
        (MESSAGE, "anyio._lazyimport", DeprecationWarning),
        (MESSAGE, "starlette.testclient_extra", DeprecationWarning),
        (MESSAGE + " Additional problem.", "starlette.testclient", DeprecationWarning),
        (MESSAGE, "starlette.testclient", UserWarning),
        ("ordinary runtime warning", "orchestwin.api", RuntimeWarning),
    ],
)
def test_other_warnings_are_still_errors(message, module, category) -> None:
    with warnings.catch_warnings():
        _apply_filters()
        with pytest.raises(category):
            warnings.warn_explicit(message, category, "probe.py", 1, module=module)


def test_real_testclient_import_and_lifespan_with_deprecated_alias_probe() -> None:
    # Reproduce the upstream warning on both old and new AnyIO installations.
    # Only the child-process module object is changed; site-packages are untouched.
    code = r"""
import builtins
import sys
import tomllib
import warnings
from pathlib import Path

config = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for specification in config["tool"]["pytest"]["ini_options"]["filterwarnings"]:
    action, message, category, module, line = (specification.split(":") + [""] * 5)[:5]
    warnings.filterwarnings(action, message, getattr(builtins, category) if category else Warning,
                            module, int(line or 0))
import anyio.abc
from anyio.from_thread import BlockingPortal
original = getattr(anyio.abc, "__getattr__", None)
anyio.abc.__dict__.pop("BlockingPortal", None)
def alias(name):
    if name == "BlockingPortal":
        warnings.warn("The anyio.abc.BlockingPortal alias is deprecated, "
                      "use anyio.from_thread.BlockingPortal instead.",
                      DeprecationWarning, stacklevel=2)
        return BlockingPortal
    if original is not None:
        return original(name)
    raise AttributeError(name)
anyio.abc.__getattr__ = alias
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI()
@app.get("/probe")
async def probe():
    return {"ok": True}
with TestClient(app) as client:
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
print("testclient_compatibility: PASSED")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-W", "error", "-c", code, str(ROOT / "pyproject.toml")],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "testclient_compatibility: PASSED" in result.stdout
